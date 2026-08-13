"""Tests for the repo_renamed worker task."""

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
    GitHubRepositoryRenamedEventModel,
)
from timessquare.worker.functions.repo_renamed import repo_renamed

DATA = Path(__file__).parent / ".." / ".." / "data"

OWNER = "Codertocat"
OLD_REPO = "Hello-World"
NEW_REPO = "Hello-World-Renamed"
REPOSITORY_ID = 186853002


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


def _payload() -> GitHubRepositoryRenamedEventModel:
    """Build the rename payload from the recorded GitHub fixture."""
    return GitHubRepositoryRenamedEventModel.model_validate_json(
        (DATA / "github_webhooks" / "repository_renamed.json").read_text()
    )


def _page(
    name: str,
    *,
    repo: str = OLD_REPO,
    repository_id: int | None = None,
) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=OWNER,
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


async def _stored_repo_name(
    process_context: ProcessContext, page_name: str
) -> str | None:
    """Read back a page's stored repository name."""
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        page = await factory.create_page_service().get_page(page_name)
        return page.github_repo
    return None


@pytest.mark.asyncio
async def test_repo_renamed_flips_names(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The task renames the repository's pages by ID and through the old
    name for pages that have no ID yet, leaving other repositories alone.

    ``respx_mock`` with no routes registered means any outbound HTTP call —
    a Noteburst execution or a GitHub content fetch — fails the test.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(
        process_context,
        [
            _page("by-id", repo="ancient-name", repository_id=REPOSITORY_ID),
            _page("unbackfilled"),
            _page("impostor", repository_id=99),
        ],
    )

    await repo_renamed(worker_ctx, payload=_payload())

    assert await _stored_repo_name(process_context, "by-id") == NEW_REPO
    assert await _stored_repo_name(process_context, "unbackfilled") == NEW_REPO
    assert await _stored_repo_name(process_context, "impostor") == OLD_REPO
    assert respx_mock.calls.call_count == 0
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_repo_renamed_logs_affected_count(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The task logs how many pages the rename affected."""
    await _add_pages(
        worker_ctx["process_context"],
        [
            _page("first", repository_id=REPOSITORY_ID),
            _page("second", repository_id=REPOSITORY_ID),
        ],
    )

    with capture_logs() as logs:
        await repo_renamed(worker_ctx, payload=_payload())

    assert any(entry.get("page_count") == 2 for entry in logs), json.dumps(
        [entry.get("event") for entry in logs]
    )
