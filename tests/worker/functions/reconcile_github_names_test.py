"""Tests for the reconcile_github_names worker cron."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import respx
import structlog
from httpx import Response
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency
from structlog.testing import capture_logs

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.worker.functions.reconcile_github_names import (
    reconcile_github_names,
)

from ...support.github import SAMPLE_PRIVATE_KEY, mock_github_repository_by_id

APP_ID = 12345
INSTALLATION_ID = 1234
REPOSITORY_ID = 42
OWNER_ID = 7

OWNER = "lsst-sqre"
"""An owner login in the default ``TS_GITHUB_ORGS``."""

OLD_REPO = "times-square-demo"
NEW_REPO = "times-square-renamed"


@pytest_asyncio.fixture
async def worker_ctx() -> AsyncGenerator[dict[str, Any]]:
    """Return an arq worker ``ctx`` over a fresh database."""
    logger = structlog.get_logger(config.logger_name)

    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    await engine.dispose()

    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    process_context = await ProcessContext.create()

    ctx: dict[str, Any] = {
        "logger": logger,
        "process_context": process_context,
        "slack": AsyncMock(),
    }
    yield ctx

    await process_context.aclose()
    await db_session_dependency.aclose()


@pytest.fixture
def github_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the GitHub App so the cron runs its reconciliation."""
    monkeypatch.setattr(config, "enable_github_app", True)
    monkeypatch.setattr(config, "github_app_id", APP_ID)
    monkeypatch.setattr(config, "github_app_private_key", SAMPLE_PRIVATE_KEY)


def _page(name: str) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=OWNER,
        github_repo=OLD_REPO,
        github_repository_id=REPOSITORY_ID,
        github_owner_id=OWNER_ID,
        github_installation_id=INSTALLATION_ID,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem=name,
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )


async def _add_pages(
    process_context: ProcessContext, pages: list[PageModel]
) -> None:
    """Add pages directly through the page store."""
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        page_service = factory.create_page_service()
        for page in pages:
            await page_service.add_page_to_store(page)
        await db_session.commit()


async def _stored_page(
    process_context: ProcessContext, page_name: str
) -> PageModel:
    """Read a page back from the database."""
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        return await factory.create_page_service().get_page(page_name)
    raise AssertionError("No database session")


@pytest.mark.asyncio
@pytest.mark.usefixtures("github_app")
async def test_reconcile_heals_offline_rename(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The cron heals a repository renamed while Times Square was offline,
    committing the new names to every one of the repository's pages.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(process_context, [_page("first"), _page("second")])
    mock_github_repository_by_id(
        respx_mock,
        repository_id=REPOSITORY_ID,
        installation_id=INSTALLATION_ID,
        owner=OWNER,
        repo=NEW_REPO,
        owner_id=OWNER_ID,
    )

    with capture_logs() as logs:
        await reconcile_github_names(worker_ctx)

    for name in ("first", "second"):
        page = await _stored_page(process_context, name)
        assert page.github_repo == NEW_REPO

    summaries = [entry for entry in logs if "repositories_checked" in entry]
    assert len(summaries) == 1
    assert summaries[0]["repositories_checked"] == 1
    assert summaries[0]["repositories_healed"] == 1
    assert summaries[0]["repositories_failed"] == 0
    assert summaries[0]["pages_updated"] == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("github_app")
async def test_reconcile_logs_but_keeps_missing_repository(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """A repository GitHub answers 404 for is logged and left alone: the cron
    never deletes pages, because a deleted repository and an uninstalled app
    look identical from here.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(process_context, [_page("kept")])
    respx_mock.post(
        "https://api.github.com/app/installations/"
        f"{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=Response(
            201,
            json={"token": "installation-token", "expires_at": "2100-01-01"},
        )
    )
    respx_mock.get(
        f"https://api.github.com/repositories/{REPOSITORY_ID}"
    ).mock(return_value=Response(404, json={"message": "Not Found"}))

    with capture_logs() as logs:
        await reconcile_github_names(worker_ctx)

    page = await _stored_page(process_context, "kept")
    assert page.github_repo == OLD_REPO
    assert page.date_deleted is None

    warnings = [entry for entry in logs if entry.get("log_level") == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["status_code"] == 404
    summaries = [entry for entry in logs if "repositories_checked" in entry]
    assert summaries[0]["repositories_failed"] == 1
    assert summaries[0]["repositories_healed"] == 0


@pytest.mark.asyncio
async def test_reconcile_skipped_without_github_app(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """Without a configured GitHub App there is nothing to reconcile against,
    so the cron reports that and makes no API calls.

    ``respx_mock`` with no routes registered means any outbound HTTP call
    fails the test.
    """
    await _add_pages(worker_ctx["process_context"], [_page("page")])

    await reconcile_github_names(worker_ctx)

    assert respx_mock.calls.call_count == 0
