"""Tests for the GitHubCheckRunService."""

from __future__ import annotations

import json
import warnings
from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
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
from safir.github.models import GitHubCheckRunConclusion, GitHubCheckRunModel
from safir.github.webhooks import (
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
)

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.githubcheckrun import (
    TRANSIENT_CHECKOUT_ERROR_MESSAGE,
    NotebookExecutionsCheck,
)
from timessquare.domain.page import PageExecutionInfo, PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.githubcheckrun import GitHubCheckRunService
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.services.page import PageService
from timessquare.storage.noteburst import NoteburstJobModel

from ..support.github import MockGitHubCheckRunAPI
from ..support.noteburst import JOB_URL

DATA = Path(__file__).parent.joinpath("../data/github_webhooks")


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instantaneous so tests do not actually wait."""
    monkeypatch.setattr(
        "timessquare.storage.github.retry._backoff_delay",
        lambda _attempt: 0.0,
    )


@pytest_asyncio.fixture
async def check_run_service() -> AsyncGenerator[GitHubCheckRunService]:
    """Return a GitHubCheckRunService wired to real services.

    The GitHub client and repository service are constructed but not
    exercised by the timeout-reporting path under test.
    """
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
        page_service = factory.create_page_service()
        github_client = GitHubAPI(process_context.http_client, "times-square")
        repo_service = GitHubRepoService(
            http_client=process_context.http_client,
            github_client=github_client,
            page_service=page_service,
            logger=logger,
        )
        yield GitHubCheckRunService(
            http_client=process_context.http_client,
            github_client=github_client,
            repo_service=repo_service,
            page_service=page_service,
            logger=logger,
        )

    await process_context.aclose()
    await db_session_dependency.aclose()


def _make_check() -> NotebookExecutionsCheck:
    """Create a NotebookExecutionsCheck from a sample check-run webhook."""
    payload_path = (
        Path(__file__).parent.parent
        / "data"
        / "github_webhooks"
        / "check_run_created.json"
    )
    event = GitHubCheckRunEventModel.model_validate(
        json.loads(payload_path.read_text())
    )
    return NotebookExecutionsCheck(event.check_run, event.repository)


def _make_page_execution() -> PageExecutionInfo:
    """Create a GitHub-backed PageExecutionInfo with a pending job."""
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    notebook = PageModel.read_ipynb(ipynb)
    parameters = PageParameters.create_from_notebook(notebook)
    page = PageModel.create_from_repo(
        ipynb=ipynb,
        title="Demo",
        parameters=parameters,
        github_owner="Codertocat",
        github_repo="Hello-World",
        repository_path_prefix="notebooks",
        repository_display_path_prefix="notebooks",
        repository_path_stem="demo",
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="abc123",
        repository_sidecar_sha="def456",
    )
    job = NoteburstJobModel.model_validate(
        {"date_submitted": datetime.now(tz=UTC), "job_url": JOB_URL}
    )
    return PageExecutionInfo(
        page=page,
        values={},
        noteburst_status_code=202,
        noteburst_job=job,
    )


@pytest.mark.asyncio
async def test_report_timeout_in_progress(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """An in-progress job at timeout reports its runtime and state, and no
    "coroutine was never awaited" warning is raised.
    """
    enqueue_time = datetime.now(tz=UTC) - timedelta(seconds=30)
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "self_url": JOB_URL,
                "enqueue_time": enqueue_time.isoformat(),
                "start_time": (
                    enqueue_time + timedelta(seconds=5)
                ).isoformat(),
                "status": "in_progress",
            },
        )
    )

    check = _make_check()
    page_execution = _make_page_execution()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await check_run_service._report_pr_notebook_timeout_errors(
            check, deque([page_execution])
        )

    coroutine_warnings = [
        w
        for w in caught
        if "coroutine" in str(w.message) and "never awaited" in str(w.message)
    ]
    assert not coroutine_warnings

    assert len(check.annotations) == 1
    message = check.annotations[0].message
    assert "still in progress" in message
    assert "seconds" in message

    assert len(check.notebook_executions) == 1
    runtime = check.notebook_executions[0].runtime
    assert runtime is not None
    assert runtime.total_seconds() > 0


@pytest.mark.asyncio
async def test_report_timeout_queued(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A queued job at timeout reports the queued state."""
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "self_url": JOB_URL,
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
            },
        )
    )

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    message = check.annotations[0].message
    assert "still in the Noteburst queue." in message


@pytest.mark.asyncio
async def test_report_timeout_noteburst_error(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A failed Noteburst status lookup still reports the timeout with no
    runtime, and no exception escapes.
    """
    respx_mock.get(JOB_URL).mock(return_value=Response(500, text="boom"))

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    assert check.annotations[0].title == "Noteburst timeout"

    assert len(check.notebook_executions) == 1
    assert check.notebook_executions[0].runtime is None


@pytest.mark.asyncio
async def test_report_timeout_noteburst_unreachable(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A transport error during the Noteburst status lookup still reports
    the timeout with no runtime, and no exception escapes.
    """
    respx_mock.get(JOB_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    assert check.annotations[0].title == "Noteburst timeout"

    assert len(check.notebook_executions) == 1
    assert check.notebook_executions[0].runtime is None


def _transient_annotation_paths(mock: MockGitHubCheckRunAPI) -> list[str]:
    """Get the paths of the transient-error annotations in the check run's
    concluding PATCH body.
    """
    annotations = mock.patched[-1]["output"]["annotations"]
    return [
        a["path"]
        for a in annotations
        if a["message"] == TRANSIENT_CHECKOUT_ERROR_MESSAGE
    ]


@pytest.mark.asyncio
async def test_notebook_check_concludes_on_transient_error(
    http_client: AsyncClient,
) -> None:
    """A persistent transient checkout failure concludes the notebook check
    with a ``failure`` conclusion rather than leaving it dangling
    ``in_progress``, and no exception propagates.
    """
    payload = GitHubCheckSuiteEventModel.model_validate(
        json.loads((DATA / "check_suite_completed.json").read_text())
    )
    check_run_data = json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]
    check_run = GitHubCheckRunModel.model_validate(check_run_data)
    mock = MockGitHubCheckRunAPI(
        check_run=check_run_data,
        contents_error=httpx.ReadTimeout("slow"),
    )

    service = GitHubCheckRunService(
        http_client=http_client,
        github_client=cast("GitHubAPI", mock),
        # The transient path returns before these services are used.
        repo_service=cast("GitHubRepoService", None),
        page_service=cast("PageService", None),
        logger=structlog.get_logger(),
    )

    await service.run_notebook_check_run(
        check_run=check_run, repo=payload.repository
    )

    # The check run was concluded with a failure rather than left in_progress.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure
    # The checkout never got as far as a specific notebook, so the annotation
    # falls back to the repository's times-square.yaml.
    assert _transient_annotation_paths(mock) == ["times-square.yaml"]


class _NoPagesPageService:
    """Stand-in for `PageService` that reports no existing pages.

    `run_notebook_check_run` only reaches `get_pages_for_repo` before it
    loads the first notebook, so that is all the notebook-loading tests
    below need from the page service.
    """

    async def get_pages_for_repo(
        self, owner: str, name: str, commit: str | None = None
    ) -> list[PageModel]:
        return []


def _make_notebook_load_service(
    *, http_client: AsyncClient, mock: MockGitHubCheckRunAPI
) -> GitHubCheckRunService:
    """Build a check-run service that reaches the notebook-loading blob
    fetches with the given mock GitHub client.
    """
    return GitHubCheckRunService(
        http_client=http_client,
        github_client=cast("GitHubAPI", mock),
        # The check returns while loading the first notebook, before any
        # page is created.
        repo_service=cast("GitHubRepoService", None),
        page_service=cast("PageService", _NoPagesPageService()),
        logger=structlog.get_logger(),
    )


@pytest.mark.asyncio
async def test_notebook_check_concludes_on_transient_blob_error(
    http_client: AsyncClient,
) -> None:
    """A persistent transient error while loading a notebook's git blobs
    concludes the notebook check with a ``failure`` conclusion rather than
    leaving it dangling ``in_progress``, and no exception propagates.
    """
    payload = GitHubCheckSuiteEventModel.model_validate(
        json.loads((DATA / "check_suite_completed.json").read_text())
    )
    check_run_data = json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]
    check_run = GitHubCheckRunModel.model_validate(check_run_data)
    mock = MockGitHubCheckRunAPI(
        check_run=check_run_data,
        blob_error=httpx.ReadTimeout("slow"),
    )
    service = _make_notebook_load_service(http_client=http_client, mock=mock)

    await service.run_notebook_check_run(
        check_run=check_run, repo=payload.repository
    )

    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure
    assert TRANSIENT_CHECKOUT_ERROR_MESSAGE in json.dumps(mock.patched[-1])
    # The annotation points at the notebook that failed to load, not at the
    # repository's times-square.yaml.
    assert _transient_annotation_paths(mock) == ["demo.ipynb"]


@pytest.mark.asyncio
async def test_notebook_check_raises_on_nontransient_blob_error(
    http_client: AsyncClient,
) -> None:
    """A non-transient error while loading a notebook's git blobs still
    propagates, so the worker's Slack alerting is unchanged for real bugs.
    """
    payload = GitHubCheckSuiteEventModel.model_validate(
        json.loads((DATA / "check_suite_completed.json").read_text())
    )
    check_run_data = json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]
    check_run = GitHubCheckRunModel.model_validate(check_run_data)
    mock = MockGitHubCheckRunAPI(
        check_run=check_run_data,
        blob_error=RuntimeError("unexpected"),
    )
    service = _make_notebook_load_service(http_client=http_client, mock=mock)

    with pytest.raises(RuntimeError, match="unexpected"):
        await service.run_notebook_check_run(
            check_run=check_run, repo=payload.repository
        )


INSTALLED_REPO = {"id": 186853002, "full_name": "Codertocat/Hello-World"}
"""The repository in the webhook fixtures, as a pull request ref's ``repo``."""

FORK_REPO = {"id": 999000111, "full_name": "mallory/Hello-World"}
"""A fork of `INSTALLED_REPO`, as a pull request ref's ``repo``."""

HEAD_SHA = "ec26c3e57ca3a959ca5aad62de7213c562f8c821"
"""The head commit in the webhook fixtures."""


def _commit_pull(
    number: int, *, head_repo: dict[str, object] | None
) -> dict[str, object]:
    """Create a pull request, as GitHub lists it for a commit, that targets
    `INSTALLED_REPO` from a branch in ``head_repo``.
    """
    return {
        "number": number,
        "head": {"sha": HEAD_SHA, "repo": head_repo},
        "base": {"sha": "f95f852bd8fca8fcc58a9a2d6c842781e32a215e"}
        | {"repo": INSTALLED_REPO},
    }


def _make_guarded_service(
    *, http_client: AsyncClient, mock: MockGitHubCheckRunAPI
) -> GitHubCheckRunService:
    """Build a check-run service for the untrusted-source guard tests, which
    never get as far as the repository or page services.
    """
    return GitHubCheckRunService(
        http_client=http_client,
        github_client=cast("GitHubAPI", mock),
        repo_service=cast("GitHubRepoService", None),
        page_service=cast("PageService", None),
        logger=structlog.get_logger(),
    )


def _check_suite_payload() -> GitHubCheckSuiteEventModel:
    return GitHubCheckSuiteEventModel.model_validate(
        json.loads((DATA / "check_suite_completed.json").read_text())
    )


def _check_run_data() -> dict[str, object]:
    return json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]


def _write_requests(mock: MockGitHubCheckRunAPI) -> list[tuple[str, str]]:
    """Get the requests that created or updated a check run."""
    return [r for r in mock.requests if r[0] in ("POST", "PATCH")]


@pytest.mark.asyncio
async def test_check_suite_skipped_for_fork_pull_request(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check suite whose head commit comes from a fork's pull request
    creates no check runs, so the fork's notebooks are never read or run.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = MockGitHubCheckRunAPI(
        check_run=_check_run_data(),
        commit_pulls=[_commit_pull(3, head_repo=FORK_REPO)],
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock) == []
    assert not any("times-square.yaml" in url for _, url in mock.requests)


@pytest.mark.asyncio
async def test_check_suite_skipped_for_unaccepted_org(
    http_client: AsyncClient,
) -> None:
    """A check suite for a repository whose owner is not in
    ``TS_GITHUB_ORGS`` creates no check runs.
    """
    assert "Codertocat" not in config.accepted_github_orgs
    mock = MockGitHubCheckRunAPI(check_run=_check_run_data())
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert mock.requests == []


@pytest.mark.asyncio
async def test_check_suite_runs_for_commit_also_in_same_repo_pull_request(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit that a pull request from the repository itself contains was
    pushed by someone with write access, so it is still checked when a fork
    opens a second pull request for the same commit.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = MockGitHubCheckRunAPI(
        check_run=_check_run_data(),
        commit_pulls=[
            _commit_pull(2, head_repo=INSTALLED_REPO),
            _commit_pull(3, head_repo=FORK_REPO),
        ],
        # An invalid sidecar fails the configs check, which ends the flow
        # before the notebook check needs the repository or page services.
        sidecar_content="enabled: [",
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock)[0] == (
        "POST",
        "https://api.github.com/repos/Codertocat/Hello-World/check-runs",
    )


@pytest.mark.asyncio
async def test_check_suite_skipped_for_deleted_fork(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pull request whose head repository is unknown, because the fork was
    deleted, is treated as coming from a fork.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = MockGitHubCheckRunAPI(
        check_run=_check_run_data(),
        commit_pulls=[_commit_pull(3, head_repo=None)],
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock) == []


@pytest.mark.asyncio
async def test_check_suite_skipped_for_pull_request_inside_fork(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pull request between two branches of a fork does not vouch for a
    commit, even though its head and base repositories match.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    pull = _commit_pull(1, head_repo=FORK_REPO)
    pull["base"] = {"sha": "f95f852", "repo": FORK_REPO}
    mock = MockGitHubCheckRunAPI(
        check_run=_check_run_data(), commit_pulls=[pull]
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock) == []


@pytest.mark.asyncio
async def test_rerequested_check_run_skipped_for_fork_pull_request(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a check run whose head commit comes from a fork's pull
    request concludes it as neutral without reading the fork's content.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    data = json.loads((DATA / "check_run_created.json").read_text())
    data["action"] = "rerequested"
    data["check_run"]["external_id"] = NotebookExecutionsCheck.external_id
    payload = GitHubCheckRunEventModel.model_validate(data)
    mock = MockGitHubCheckRunAPI(
        check_run=data["check_run"],
        commit_pulls=[_commit_pull(3, head_repo=FORK_REPO)],
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(payload=payload)

    assert [p["conclusion"] for p in mock.patched] == [
        GitHubCheckRunConclusion.neutral
    ]
    assert not any("times-square.yaml" in url for _, url in mock.requests)
