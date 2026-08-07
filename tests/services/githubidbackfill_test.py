"""Tests for the GitHub numeric ID backfill service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import respx
import structlog
from httpx import AsyncClient, Response
from safir.database import (
    create_async_session,
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.github import GitHubAppClientFactory
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.services.githubidbackfill import GitHubIdBackfillService
from timessquare.storage.page import PageStore

from ..support.github import SAMPLE_PRIVATE_KEY, mock_github_app_repository

APP_ID = 12345


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Return a database session against a freshly initialized schema."""
    logger = structlog.get_logger(config.logger_name)
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    db_session = await create_async_session(engine)
    try:
        yield db_session
    finally:
        await db_session.aclose()
        await engine.dispose()


def _page(name: str, *, owner: str, repo: str) -> PageModel:
    """Build a GitHub-backed page with no numeric IDs recorded."""
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo=repo,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem=name,
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )


def _service(
    store: PageStore, http_client: AsyncClient
) -> GitHubIdBackfillService:
    """Build a backfill service reading through the mocked GitHub API."""
    return GitHubIdBackfillService(
        page_store=store,
        github_client_factory=GitHubAppClientFactory(
            id=APP_ID,
            key=SAMPLE_PRIVATE_KEY,
            name="lsst-sqre/times-square",
            http_client=http_client,
        ),
        logger=structlog.get_logger(config.logger_name),
    )


@pytest.mark.asyncio
async def test_backfill_fills_ids(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """The backfill resolves each repository through the GitHub App and
    records its repository, owner, and installation IDs on the repository's
    pages.
    """
    store = PageStore(session=session)
    store.add(_page("demo", owner="lsst-sqre", repo="times-square-demo"))
    await session.commit()
    mock_github_app_repository(
        respx_mock,
        owner="lsst-sqre",
        repo="times-square-demo",
        installation_id=1234,
        repository_id=42,
        owner_id=7,
    )

    report = await _service(store, http_client).backfill()
    await session.commit()

    assert report.repositories_resolved == 1
    assert report.repositories_skipped == 0
    assert report.pages_updated == 1
    page = await store.get("demo")
    assert page is not None
    assert page.github_repository_id == 42
    assert page.github_owner_id == 7
    assert page.github_installation_id == 1234


@pytest.mark.asyncio
async def test_backfill_dry_run_writes_nothing(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A dry run reports the pages it would fill without touching them."""
    store = PageStore(session=session)
    store.add(_page("demo", owner="lsst-sqre", repo="times-square-demo"))
    store.add(_page("other", owner="lsst-sqre", repo="times-square-demo"))
    await session.commit()
    mock_github_app_repository(
        respx_mock,
        owner="lsst-sqre",
        repo="times-square-demo",
        installation_id=1234,
        repository_id=42,
        owner_id=7,
    )

    report = await _service(store, http_client).backfill(dry_run=True)
    await session.commit()

    assert report.dry_run is True
    assert report.repositories_resolved == 1
    assert report.pages_updated == 2
    page = await store.get("demo")
    assert page is not None
    assert page.github_repository_id is None
    assert page.github_owner_id is None
    assert page.github_installation_id is None


@pytest.mark.asyncio
async def test_backfill_skips_unresolvable_repository(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A repository the GitHub App cannot see is logged and skipped, and the
    run carries on to the repositories it can resolve.
    """
    store = PageStore(session=session)
    store.add(_page("gone", owner="lsst-sqre", repo="deleted-repo"))
    store.add(_page("demo", owner="lsst-sqre", repo="times-square-demo"))
    await session.commit()
    respx_mock.get(
        "https://api.github.com/repos/lsst-sqre/deleted-repo/installation"
    ).mock(return_value=Response(404, json={"message": "Not Found"}))
    mock_github_app_repository(
        respx_mock,
        owner="lsst-sqre",
        repo="times-square-demo",
        installation_id=1234,
        repository_id=42,
        owner_id=7,
    )

    with capture_logs() as logs:
        report = await _service(store, http_client).backfill()
    await session.commit()

    assert report.repositories_resolved == 1
    assert report.repositories_skipped == 1
    assert report.pages_updated == 1
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["github_repo"] == "deleted-repo"
    assert warnings[0]["status_code"] == 404
    skipped = await store.get("gone")
    assert skipped is not None
    assert skipped.github_repository_id is None
    filled = await store.get("demo")
    assert filled is not None
    assert filled.github_repository_id == 42
