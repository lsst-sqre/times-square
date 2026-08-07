"""Tests for the GitHub repository name reconciliation service."""

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
from timessquare.services.githubnamereconcile import (
    GitHubNameReconciliationService,
)
from timessquare.storage.page import PageStore

from ..support.github import SAMPLE_PRIVATE_KEY, mock_github_repository_by_id

APP_ID = 12345
INSTALLATION_ID = 1234
REPOSITORY_ID = 42
OWNER_ID = 7

ACCEPTED_OWNER = "lsst-sqre"
"""An owner login in the default ``TS_GITHUB_ORGS``."""


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


def _page(
    name: str,
    *,
    owner: str = ACCEPTED_OWNER,
    repo: str = "times-square-demo",
    repository_id: int = REPOSITORY_ID,
    owner_id: int | None = OWNER_ID,
    installation_id: int = INSTALLATION_ID,
) -> PageModel:
    """Build a GitHub-backed page with its numeric IDs recorded."""
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo=repo,
        github_repository_id=repository_id,
        github_owner_id=owner_id,
        github_installation_id=installation_id,
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
) -> GitHubNameReconciliationService:
    """Build a reconciliation service reading through the mocked GitHub
    API.
    """
    return GitHubNameReconciliationService(
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
async def test_reconcile_heals_renamed_repository(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A repository renamed while Times Square was offline is healed from the
    names GitHub answers with, keyed on its stable repository ID.
    """
    store = PageStore(session=session)
    store.add(_page("first"))
    store.add(_page("second"))
    await session.commit()
    mock_github_repository_by_id(
        respx_mock,
        repository_id=REPOSITORY_ID,
        installation_id=INSTALLATION_ID,
        owner=ACCEPTED_OWNER,
        repo="times-square-renamed",
        owner_id=OWNER_ID,
    )

    report = await _service(store, http_client).reconcile()
    await session.commit()

    assert report.repositories_checked == 1
    assert report.repositories_healed == 1
    assert report.repositories_failed == 0
    assert report.pages_updated == 2
    for name in ("first", "second"):
        page = await store.get(name)
        assert page is not None
        assert page.github_repo == "times-square-renamed"


@pytest.mark.asyncio
async def test_reconcile_leaves_current_names_alone(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A repository whose stored names still match GitHub is checked but not
    counted as healed.
    """
    store = PageStore(session=session)
    store.add(_page("current"))
    await session.commit()
    mock_github_repository_by_id(
        respx_mock,
        repository_id=REPOSITORY_ID,
        installation_id=INSTALLATION_ID,
        owner=ACCEPTED_OWNER,
        repo="times-square-demo",
        owner_id=OWNER_ID,
    )

    report = await _service(store, http_client).reconcile()
    await session.commit()

    assert report.repositories_checked == 1
    assert report.repositories_healed == 0
    assert report.pages_updated == 0


@pytest.mark.asyncio
async def test_reconcile_logs_and_keeps_missing_repository(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A repository GitHub answers 404 for is logged as a warning and its
    pages are left exactly as they are — never deleted.
    """
    store = PageStore(session=session)
    store.add(_page("kept"))
    await session.commit()
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
        report = await _service(store, http_client).reconcile()
    await session.commit()

    assert report.repositories_checked == 1
    assert report.repositories_healed == 0
    assert report.repositories_failed == 1
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["status_code"] == 404
    assert warnings[0]["github_repository_id"] == REPOSITORY_ID
    page = await store.get("kept")
    assert page is not None
    assert page.github_repo == "times-square-demo"
    assert page.date_deleted is None


@pytest.mark.asyncio
async def test_reconcile_skips_unaccepted_owner(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A repository that has drifted out of ``TS_GITHUB_ORGS`` is reported
    rather than healed into an organization Times Square does not sync.
    """
    store = PageStore(session=session)
    store.add(_page("orphaned"))
    await session.commit()
    mock_github_repository_by_id(
        respx_mock,
        repository_id=REPOSITORY_ID,
        installation_id=INSTALLATION_ID,
        owner="some-other-org",
        repo="times-square-demo",
        owner_id=OWNER_ID,
    )

    with capture_logs() as logs:
        report = await _service(store, http_client).reconcile()
    await session.commit()

    assert report.repositories_checked == 1
    assert report.repositories_healed == 0
    assert report.repositories_skipped == 1
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["accepted_orgs"] == config.accepted_github_orgs
    page = await store.get("orphaned")
    assert page is not None
    assert page.github_owner == ACCEPTED_OWNER


@pytest.mark.asyncio
async def test_reconcile_continues_past_failures(
    session: AsyncSession, http_client: AsyncClient, respx_mock: respx.Router
) -> None:
    """One unreachable repository does not stop the run from healing the
    repositories that follow it.
    """
    store = PageStore(session=session)
    store.add(_page("unreachable", repo="a-broken-repo", repository_id=99))
    store.add(_page("healed"))
    await session.commit()
    respx_mock.post(
        "https://api.github.com/app/installations/"
        f"{INSTALLATION_ID}/access_tokens"
    ).mock(
        return_value=Response(
            201,
            json={"token": "installation-token", "expires_at": "2100-01-01"},
        )
    )
    respx_mock.get("https://api.github.com/repositories/99").mock(
        return_value=Response(410, json={"message": "Gone"})
    )
    mock_github_repository_by_id(
        respx_mock,
        repository_id=REPOSITORY_ID,
        installation_id=INSTALLATION_ID,
        owner=ACCEPTED_OWNER,
        repo="times-square-renamed",
        owner_id=OWNER_ID,
    )

    report = await _service(store, http_client).reconcile()
    await session.commit()

    assert report.repositories_checked == 2
    assert report.repositories_failed == 1
    assert report.repositories_healed == 1
    page = await store.get("healed")
    assert page is not None
    assert page.github_repo == "times-square-renamed"
