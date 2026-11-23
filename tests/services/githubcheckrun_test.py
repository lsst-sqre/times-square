"""Tests for the GitHubCheckRunService."""

from __future__ import annotations

import json
import warnings
from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
import respx
import structlog
from gidgethub import HTTPException
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
    GitHubConfigsCheck,
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
"""The repository in the webhook fixtures, as a pull request ref's ``repo``.

Its default branch is ``master``.
"""

FORK_REPO = {"id": 999000111, "full_name": "mallory/Hello-World"}
"""A fork of `INSTALLED_REPO`, as a pull request ref's ``repo``."""

UPSTREAM_REPO = {"id": 999000222, "full_name": "octo-org/Hello-World"}
"""A repository that `INSTALLED_REPO` is itself a fork of."""

HEAD_SHA = "ec26c3e57ca3a959ca5aad62de7213c562f8c821"
"""The head commit in the webhook fixtures."""

BASE_SHA = "f95f852bd8fca8fcc58a9a2d6c842781e32a215e"
"""An older commit that the branches in these tests start from."""

NEWER_SHA = "3c1e4b8f0d9a7e6c5b4a39281706f5e4d3c2b1a0"
"""A commit pushed on top of `HEAD_SHA`."""

FORK_BRANCH_NAMES: list[str | None] = [
    None,
    "changes",
    "master",
    "trunk",
    "pull/3/head",
]
"""Head branches that a check suite for a fork's commit might report.

GitHub reports no head branch for a third-party app's check suite, such as
Times Square's, on a fork's commit. GitHub Actions' check suites report the
name of the fork's branch, so the names cover one the installed repository
lacks, one it shares, one it has since renamed (see `FORK_RENAMED_BRANCHES`),
and one that names the pull request's own ref in the installed repository,
which the compare API would resolve to the fork's commit.
"""

FORK_RENAMED_BRANCHES = {"trunk": "master"}
"""Branches of the installed repository renamed after a fork was made, so the
fork still has a branch under the old name.
"""


def _pull_request(
    number: int,
    *,
    head_repo: dict[str, object] | None,
    base_repo: dict[str, object] = INSTALLED_REPO,
    merged: bool = False,
) -> dict[str, object]:
    """Create a pull request whose head is `HEAD_SHA`, as GitHub lists it
    for a commit. A ``head_repo`` of `None` is how GitHub reports the head of
    a pull request whose fork has been deleted.
    """
    return {
        "number": number,
        "state": "closed" if merged else "open",
        "merged_at": "2026-11-20T12:00:00Z" if merged else None,
        "head": {"sha": HEAD_SHA, "repo": head_repo},
        "base": {"sha": BASE_SHA, "repo": base_repo},
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


def _rerequested_payload(external_id: str) -> GitHubCheckRunEventModel:
    """Create a ``check_run`` (rerequested) payload for `HEAD_SHA`."""
    data = json.loads((DATA / "check_run_created.json").read_text())
    data["action"] = "rerequested"
    data["check_run"]["external_id"] = external_id
    return GitHubCheckRunEventModel.model_validate(data)


def _make_mock(**kwargs: Any) -> MockGitHubCheckRunAPI:
    """Create a mock GitHub API for a check of `HEAD_SHA`.

    An invalid sidecar fails the configs check, which ends a check suite's
    flow before the notebook check needs the repository or page services.
    """
    return MockGitHubCheckRunAPI(
        check_run=_check_run_data(), sidecar_content="enabled: [", **kwargs
    )


def _write_requests(mock: MockGitHubCheckRunAPI) -> list[tuple[str, str]]:
    """Get the requests that created or updated a check run."""
    return [r for r in mock.requests if r[0] in ("POST", "PATCH")]


def _read_notebooks(mock: MockGitHubCheckRunAPI) -> bool:
    """Determine whether the repository's Times Square content was read."""
    return any("times-square.yaml" in url for _, url in mock.requests)


def _created_check_runs(mock: MockGitHubCheckRunAPI) -> list[str]:
    """Get the names of the check runs that were created."""
    return [body["name"] for body in mock.posted]


def _was_skipped(mock: MockGitHubCheckRunAPI) -> bool:
    """Determine whether a check run was concluded as skipped."""
    return any(
        (body.get("output") or {}).get("title") == "Skipped"
        for body in mock.patched
    )


def _assert_skipped_as_not_on_branch(mock: MockGitHubCheckRunAPI) -> None:
    """Assert that a check run was concluded as skipped, with a summary that
    gives both reasons a commit can be missing from the repository's
    branches.
    """
    assert [p["conclusion"] for p in mock.patched] == [
        GitHubCheckRunConclusion.neutral
    ]
    assert _was_skipped(mock)
    summary = mock.patched[0]["output"]["summary"]
    assert "not on a branch of this repository" in summary
    assert "fork" in summary
    assert "deleted" in summary


@pytest.mark.asyncio
@pytest.mark.parametrize("fork_branch", FORK_BRANCH_NAMES)
async def test_check_suite_skipped_for_fork_pull_request(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fork_branch: str | None,
) -> None:
    """A check suite for the head commit of an open pull request from a fork
    creates no check runs, so the fork's notebooks are never read or run.

    Through the base repository, GitHub lists no pull requests and no
    branches for a fork's commit, and its check suite reports either no head
    branch or the name of the fork's branch.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [BASE_SHA]},
        renamed_branches=FORK_RENAMED_BRANCHES,
        pull_heads={3: HEAD_SHA},
        check_suite_head_branch=fork_branch,
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock) == []
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
@pytest.mark.parametrize("fork_branch", FORK_BRANCH_NAMES)
async def test_rerequested_check_run_skipped_for_fork_pull_request(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fork_branch: str | None,
) -> None:
    """Re-running a check run on the head commit of an open pull request
    from a fork concludes it as skipped without reading the fork's content.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [BASE_SHA]},
        renamed_branches=FORK_RENAMED_BRANCHES,
        pull_heads={3: HEAD_SHA},
        check_suite_head_branch=fork_branch,
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(NotebookExecutionsCheck.external_id)
    )

    _assert_skipped_as_not_on_branch(mock)
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
async def test_rerequested_check_run_skipped_for_deleted_commit(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a check run on a commit that was pushed to the repository
    but is no longer on any of its branches concludes it as skipped without
    reading its content.

    This is the head commit of a pull request that was squash or rebase
    merged, so the default branch has a new commit in its place, and whose
    branch was then deleted. GitHub serves such a commit just as it does a
    fork's, so it fails the same guard, and the summary says it may have been
    deleted rather than blaming forks alone.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [NEWER_SHA, BASE_SHA]},
        check_suite_head_branch="changes",
    )
    comparison = await mock.getitem(
        f"repos/Codertocat/Hello-World/compare/{NEWER_SHA}...{HEAD_SHA}"
    )
    assert comparison["status"] == "diverged"
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(NotebookExecutionsCheck.external_id)
    )

    _assert_skipped_as_not_on_branch(mock)
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
@pytest.mark.parametrize("fork_branch", FORK_BRANCH_NAMES)
async def test_check_suite_skipped_for_fork_commit_on_branch_tip(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fork_branch: str | None,
) -> None:
    """A check suite for a fork's commit that was made on top of the tip of
    the default branch creates no check runs.

    GitHub compares such a commit as ``ahead`` of the branch, rather than
    ``diverged``.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [BASE_SHA]},
        renamed_branches=FORK_RENAMED_BRANCHES,
        fork_commits={HEAD_SHA: BASE_SHA},
        pull_heads={3: HEAD_SHA},
        check_suite_head_branch=fork_branch,
    )
    comparison = await mock.getitem(
        f"repos/Codertocat/Hello-World/compare/{BASE_SHA}...{HEAD_SHA}"
    )
    assert comparison["status"] == "ahead"
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _write_requests(mock) == []
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [HTTPStatus.FORBIDDEN, HTTPStatus.BAD_GATEWAY]
)
@pytest.mark.parametrize(
    "lookup",
    [
        r"/branches-where-head$",
        r"/check-suites/\d+$",
        r"/branches/master$",
        r"/compare/",
    ],
    ids=["branches-where-head", "check-suite", "branch", "compare"],
)
async def test_check_suite_fails_closed_on_provenance_lookup_error(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    lookup: str,
    status: HTTPStatus,
) -> None:
    """An error other than not found or a redirect from any of the lookups
    that decide whether a commit may be checked propagates, and no check runs
    are created, even for a commit that would otherwise be checked.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [NEWER_SHA, HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="master",
        error_statuses={lookup: status},
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    with pytest.raises(HTTPException) as excinfo:
        await service.initiate_check_runs(payload=_check_suite_payload())

    assert excinfo.value.status_code == status
    assert _write_requests(mock) == []
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
async def test_check_suite_skipped_for_unaccepted_org(
    http_client: AsyncClient,
) -> None:
    """A check suite for a repository whose owner is not in
    ``TS_GITHUB_ORGS`` creates no check runs.
    """
    assert "Codertocat" not in config.accepted_github_orgs
    mock = _make_mock(branches={"changes": [HEAD_SHA]})
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert mock.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fork", [FORK_REPO, None], ids=["fork-exists", "fork-deleted"]
)
async def test_check_suite_runs_for_merged_fork_pull_request(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fork: dict[str, object] | None,
) -> None:
    """A default-branch commit that arrived through a merged pull request
    from a fork, whether or not the fork still exists, gets both check runs.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="master",
        commit_pulls={
            HEAD_SHA: [_pull_request(3, head_repo=fork, merged=True)]
        },
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _created_check_runs(mock) == [
        GitHubConfigsCheck.title,
        NotebookExecutionsCheck.title,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fork", [FORK_REPO, None], ids=["fork-exists", "fork-deleted"]
)
async def test_rerequested_check_run_runs_for_merged_fork_pull_request(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fork: dict[str, object] | None,
) -> None:
    """Re-running a check run on a default-branch commit that arrived through
    a merged pull request from a fork runs the check, even after the default
    branch has moved on.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [NEWER_SHA, HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="master",
        commit_pulls={
            HEAD_SHA: [_pull_request(3, head_repo=fork, merged=True)]
        },
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(GitHubConfigsCheck.external_id)
    )

    assert _read_notebooks(mock)
    assert not _was_skipped(mock)


@pytest.mark.asyncio
async def test_check_suite_runs_for_installed_fork_with_upstream_pull_request(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit pushed to a branch of an installed repository that is itself
    a fork gets both check runs, even when that branch has an open pull
    request to the upstream repository.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [BASE_SHA], "changes": [HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="changes",
        commit_pulls={
            HEAD_SHA: [
                _pull_request(
                    7, head_repo=INSTALLED_REPO, base_repo=UPSTREAM_REPO
                )
            ]
        },
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _created_check_runs(mock) == [
        GitHubConfigsCheck.title,
        NotebookExecutionsCheck.title,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pulls",
    [
        [],
        [_pull_request(2, head_repo=INSTALLED_REPO)],
        [
            _pull_request(2, head_repo=INSTALLED_REPO),
            _pull_request(3, head_repo=FORK_REPO),
        ],
    ],
    ids=[
        "no-pull-request",
        "same-repo-pull-request",
        "also-fork-pull-request",
    ],
)
async def test_check_suite_runs_for_same_repo_commit(
    http_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    pulls: list[dict[str, object]],
) -> None:
    """A commit pushed to a branch of the repository gets both check runs,
    with or without a pull request, and even when a fork has opened a pull
    request for the same commit.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [BASE_SHA], "changes": [HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="changes",
        commit_pulls={HEAD_SHA: pulls},
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.initiate_check_runs(payload=_check_suite_payload())

    assert _created_check_runs(mock) == [
        GitHubConfigsCheck.title,
        NotebookExecutionsCheck.title,
    ]


@pytest.mark.asyncio
async def test_rerequested_check_run_runs_for_older_branch_commit(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a check run on a commit that is no longer the head of its
    branch, because more commits were pushed on top of it, runs the check.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={
            "master": [BASE_SHA],
            "changes": [NEWER_SHA, HEAD_SHA, BASE_SHA],
        },
        check_suite_head_branch="changes",
        commit_pulls={HEAD_SHA: [_pull_request(2, head_repo=INSTALLED_REPO)]},
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(GitHubConfigsCheck.external_id)
    )

    assert _read_notebooks(mock)
    assert not _was_skipped(mock)


@pytest.mark.asyncio
async def test_rerequested_check_run_runs_for_commit_of_deleted_branch(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a check run on a commit whose branch was merged into the
    default branch and then deleted runs the check, since the commit is on
    the default branch.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [NEWER_SHA, HEAD_SHA, BASE_SHA]},
        check_suite_head_branch="changes",
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(GitHubConfigsCheck.external_id)
    )

    assert _read_notebooks(mock)
    assert not _was_skipped(mock)


@pytest.mark.asyncio
async def test_rerequested_check_run_runs_for_commit_of_renamed_branch(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a check run on a default-branch commit whose check suite
    names the default branch's old name runs the check.

    GitHub answers a lookup of a renamed branch's old name with a redirect to
    its new name.
    """
    monkeypatch.setattr(config, "github_orgs", "Codertocat")
    mock = _make_mock(
        branches={"master": [NEWER_SHA, HEAD_SHA, BASE_SHA]},
        renamed_branches={"trunk": "master"},
        check_suite_head_branch="trunk",
    )
    service = _make_guarded_service(http_client=http_client, mock=mock)

    await service.create_rerequested_check_run(
        payload=_rerequested_payload(GitHubConfigsCheck.external_id)
    )

    assert _read_notebooks(mock)
    assert not _was_skipped(mock)
