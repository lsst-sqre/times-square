"""Tests for the repo_transferred worker task."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import respx
import structlog
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
from timessquare.storage.github.apimodels import (
    GitHubRepositoryTransferredEventModel,
)
from timessquare.worker.functions.repo_transferred import repo_transferred

DATA = Path(__file__).parent / ".." / ".." / "data"

OLD_OWNER = "Codertocat"
NEW_OWNER = "lsst-sqre"
"""The fixture's new owner, which is in the default ``TS_GITHUB_ORGS``."""

UNACCEPTED_OWNER = "some-other-org"
REPO = "times-square-demo"
REPOSITORY_ID = 186853002
NEW_OWNER_ID = 30830384


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


def _payload(
    *, new_owner: str = NEW_OWNER
) -> GitHubRepositoryTransferredEventModel:
    """Build the transfer payload from the recorded GitHub fixture,
    optionally re-pointing it at a different new owner.
    """
    payload = json.loads(
        (DATA / "github_webhooks" / "repository_transferred.json").read_text()
    )
    payload["repository"]["owner"]["login"] = new_owner
    return GitHubRepositoryTransferredEventModel.model_validate(payload)


def _page(
    name: str,
    *,
    owner: str = OLD_OWNER,
    repo: str = "old-name",
    repository_id: int | None = None,
) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo=repo,
        github_repository_id=repository_id,
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
async def test_repo_transferred_within_accepted_orgs(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """A transfer to an accepted owner rewrites the owner, owner ID, and
    repository name on the repository's pages, matching them by repository ID
    alone.

    ``respx_mock`` with no routes registered means any outbound HTTP call —
    a Noteburst execution or a GitHub content fetch — fails the test.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(
        process_context,
        [
            _page("transferred", repository_id=REPOSITORY_ID),
            _page("elsewhere", repository_id=99),
        ],
    )

    await repo_transferred(worker_ctx, payload=_payload())

    page = await _stored_page(process_context, "transferred")
    assert page.github_owner == NEW_OWNER
    assert page.github_owner_id == NEW_OWNER_ID
    assert page.github_repo == REPO
    assert page.date_deleted is None

    other = await _stored_page(process_context, "elsewhere")
    assert other.github_owner == OLD_OWNER

    assert respx_mock.calls.call_count == 0
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_repo_transferred_has_no_name_fallback(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """Pages that predate ID capture are not swept up by a transfer: GitHub
    frees the old owner/repo name pair immediately, so a name-keyed match
    could rewrite another repository's pages.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(process_context, [_page("unbackfilled")])

    await repo_transferred(worker_ctx, payload=_payload())

    page = await _stored_page(process_context, "unbackfilled")
    assert page.github_owner == OLD_OWNER
    assert page.github_repo == "old-name"
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
async def test_repo_transferred_to_unaccepted_owner_soft_deletes(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """A transfer to an owner outside ``TS_GITHUB_ORGS`` soft-deletes the
    repository's pages, the same as uninstalling the app from it.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(
        process_context,
        [
            _page("departing", repository_id=REPOSITORY_ID),
            _page("elsewhere", repository_id=99),
        ],
    )

    await repo_transferred(
        worker_ctx, payload=_payload(new_owner=UNACCEPTED_OWNER)
    )

    page = await _stored_page(process_context, "departing")
    assert page.date_deleted is not None
    assert page.github_owner == OLD_OWNER

    other = await _stored_page(process_context, "elsewhere")
    assert other.date_deleted is None

    assert respx_mock.calls.call_count == 0
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_repo_transferred_logs_affected_count(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The task logs how many pages the transfer affected."""
    await _add_pages(
        worker_ctx["process_context"],
        [
            _page("first", repository_id=REPOSITORY_ID),
            _page("second", repository_id=REPOSITORY_ID),
        ],
    )

    with capture_logs() as logs:
        await repo_transferred(worker_ctx, payload=_payload())

    assert any(entry.get("page_count") == 2 for entry in logs), json.dumps(
        [entry.get("event") for entry in logs]
    )
