"""Tests for the GitHubRepoService's capture of stable GitHub IDs."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
import respx
import structlog
from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient, Response
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.page import PageModel
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.services.page import PageService
from timessquare.storage.github.apimodels import GitHubPushEventWithIdModel
from timessquare.storage.github.settingsfiles import NotebookSidecarFile

from ..support.github import MockGitHubRepoSyncAPI

DATA = Path(__file__).parent / ".." / "data"

REPOSITORY_ID = 186853002
"""The repository ID in the push_event.json fixture."""

OWNER_ID = 21031067
"""The repository owner's ID in the push_event.json fixture."""

INSTALLATION_ID = 4242


@dataclass
class RepoSyncHarness:
    """The collaborators a GitHubRepoService sync test needs."""

    page_service: PageService
    session: AsyncSession
    http_client: AsyncClient

    def repo_service(
        self,
        github_client: MockGitHubRepoSyncAPI,
        *,
        installation_id: int | None = None,
    ) -> GitHubRepoService:
        """Create a GitHubRepoService reading through ``github_client``."""
        return GitHubRepoService(
            http_client=self.http_client,
            github_client=cast("GitHubAPI", github_client),
            page_service=self.page_service,
            logger=structlog.get_logger(config.logger_name),
            installation_id=installation_id,
        )


@pytest_asyncio.fixture
async def harness() -> AsyncGenerator[RepoSyncHarness]:
    """Return a harness with real page storage over a fresh database."""
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

    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        yield RepoSyncHarness(
            page_service=factory.create_page_service(),
            session=db_session,
            http_client=process_context.http_client,
        )

    await process_context.aclose()
    await db_session_dependency.aclose()


def _push_payload() -> GitHubPushEventWithIdModel:
    """Build a push event payload from the recorded GitHub fixture."""
    payload = json.loads(
        (DATA / "github_webhooks" / "push_event.json").read_text()
    )
    payload["installation"]["id"] = INSTALLATION_ID
    payload["ref"] = "refs/heads/master"
    return GitHubPushEventWithIdModel.model_validate(payload)


def _github_client() -> MockGitHubRepoSyncAPI:
    """Return a mock GitHub API serving the demo notebook and its sidecar."""
    return MockGitHubRepoSyncAPI(
        notebook_source=(DATA / "demo.ipynb").read_text(),
        sidecar_content=(DATA / "times-square-demo" / "demo.yaml").read_text(),
    )


def _mock_noteburst(respx_mock: respx.Router) -> None:
    """Accept the noteburst execution requests a sync makes."""
    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )


def _existing_page(
    name: str,
    *,
    owner: str,
    repo: str,
    repository_id: int | None = REPOSITORY_ID,
) -> PageModel:
    """Build a page that already matches the synced notebook's content."""
    sidecar = NotebookSidecarFile.parse_yaml(
        (DATA / "times-square-demo" / "demo.yaml").read_text()
    )
    return PageModel(
        name=name,
        ipynb=(DATA / "demo.ipynb").read_text(),
        parameters=sidecar.export_parameters(),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo=repo,
        github_repository_id=repository_id,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem="demo",
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="notebooksha",
        repository_sidecar_sha="sidecarsha",
    )


@pytest.mark.asyncio
async def test_sync_from_push_captures_ids(
    harness: RepoSyncHarness, respx_mock: respx.Router
) -> None:
    """A push sync records the repository, owner, and installation IDs on
    the pages it creates.
    """
    _mock_noteburst(respx_mock)
    repo_service = harness.repo_service(_github_client())

    async with harness.session.begin():
        await repo_service.sync_from_push(_push_payload())

    async with harness.session.begin():
        pages = await harness.page_service.get_pages_for_repo(
            owner="Codertocat", name="Hello-World"
        )

    assert len(pages) == 1
    assert pages[0].github_repository_id == REPOSITORY_ID
    assert pages[0].github_owner_id == OWNER_ID
    assert pages[0].github_installation_id == INSTALLATION_ID


@pytest.mark.asyncio
async def test_sync_heals_drifted_names(
    harness: RepoSyncHarness, respx_mock: respx.Router
) -> None:
    """A sync of a repository whose stored owner/repo strings drifted while
    Times Square was offline heals them through the stable repository ID,
    without duplicating the page.
    """
    _mock_noteburst(respx_mock)
    async with harness.session.begin():
        await harness.page_service.add_page_to_store(
            _existing_page("renamed", owner="OldOwner", repo="old-name")
        )

    repo_service = harness.repo_service(_github_client())
    async with harness.session.begin():
        await repo_service.sync_from_push(_push_payload())

    async with harness.session.begin():
        page = await harness.page_service.get_page("renamed")
        pages = await harness.page_service.get_pages_for_repo(
            owner="Codertocat", name="Hello-World"
        )

    assert page.github_owner == "Codertocat"
    assert page.github_repo == "Hello-World"
    assert page.github_repository_id == REPOSITORY_ID
    assert page.github_owner_id == OWNER_ID
    assert page.github_installation_id == INSTALLATION_ID
    assert [p.name for p in pages] == ["renamed"]


@pytest.mark.asyncio
async def test_sync_skipped_when_names_belong_to_another_repository(
    harness: RepoSyncHarness, respx_mock: respx.Router
) -> None:
    """A push whose owner/repo names are still held by a different
    repository ID is skipped with a warning, so a recycled repository name
    cannot collide with the older repository's pages.

    Noteburst is deliberately left unmocked: a skipped sync must not create
    or execute any page.
    """
    async with harness.session.begin():
        await harness.page_service.add_page_to_store(
            _existing_page(
                "squatter",
                owner="Codertocat",
                repo="Hello-World",
                repository_id=REPOSITORY_ID + 1,
            )
        )

    repo_service = harness.repo_service(_github_client())
    with capture_logs() as logs:
        async with harness.session.begin():
            await repo_service.sync_from_push(_push_payload())

    async with harness.session.begin():
        pages = await harness.page_service.get_pages_for_repo(
            owner="Codertocat", name="Hello-World"
        )

    assert [page.name for page in pages] == ["squatter"]
    assert pages[0].github_repository_id == REPOSITORY_ID + 1
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["conflicting_repository_ids"] == [REPOSITORY_ID + 1]
    assert warnings[0]["github_repository_id"] == REPOSITORY_ID


@pytest.mark.asyncio
async def test_sync_from_repo_installation_captures_ids(
    harness: RepoSyncHarness, respx_mock: respx.Router
) -> None:
    """An app-installation sync records the same IDs as a push sync, taking
    the installation ID from the service it was built for.
    """
    _mock_noteburst(respx_mock)
    repository = json.loads(
        (DATA / "github_webhooks" / "push_event.json").read_text()
    )["repository"]
    github_client = MockGitHubRepoSyncAPI(
        notebook_source=(DATA / "demo.ipynb").read_text(),
        sidecar_content=(DATA / "times-square-demo" / "demo.yaml").read_text(),
        repository=repository,
    )
    repo_service = harness.repo_service(
        github_client, installation_id=INSTALLATION_ID
    )

    async with harness.session.begin():
        await repo_service.sync_from_repo_installation(
            "Codertocat", "Hello-World"
        )

    async with harness.session.begin():
        pages = await harness.page_service.get_pages_for_repo(
            owner="Codertocat", name="Hello-World"
        )

    assert len(pages) == 1
    assert pages[0].github_repository_id == REPOSITORY_ID
    assert pages[0].github_owner_id == OWNER_ID
    assert pages[0].github_installation_id == INSTALLATION_ID
