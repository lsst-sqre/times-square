"""Tests for the create_check_run worker task, which defers a check suite
whose commit GitHub may not show on its branch yet.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import (
    AsyncGenerator,
    Callable,
    Iterator,
    Mapping,
    Sequence,
)
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import structlog
from arq import Retry
from gidgethub.httpx import GitHubAPI
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency
from safir.github.models import GitHubCheckRunConclusion
from safir.github.webhooks import GitHubCheckRunEventModel
from structlog.testing import capture_logs

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.githubcheckrun import (
    GitHubConfigsCheck,
    NotebookExecutionsCheck,
)
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.githubcheckrun import (
    CheckSuiteOutcome,
    GitHubCheckRunService,
)
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.services.page import PageService
from timessquare.storage.github.apimodels import (
    GitHubCheckSuiteEventWithNullableBranchModel,
)
from timessquare.worker.functions.create_check_run import (
    NOT_VISIBLE_RETRIES,
    create_check_run,
)
from timessquare.worker.functions.create_rerequested_check_run import (
    create_rerequested_check_run,
)

from ...support.github import DATA, MockGitHubCheckRunAPI

WEBHOOKS = DATA / "github_webhooks"

HEAD_SHA = "ec26c3e57ca3a959ca5aad62de7213c562f8c821"
"""The head commit in the webhook fixtures, pushed to the ``changes``
branch.
"""

BASE_SHA = "f95f852bd8fca8fcc58a9a2d6c842781e32a215e"
"""The parent of `HEAD_SHA`, which was the head of ``changes`` before the
push, and is the head of the default branch, ``master``.
"""


@pytest_asyncio.fixture
async def worker_ctx() -> AsyncGenerator[dict[str, Any]]:
    """Return an arq worker ``ctx`` with a mock Slack client.

    The context wires up the database and a `ProcessContext` the way the real
    worker startup does, plus a mock Slack client so tests can assert whether
    the worker-exception Slack message was posted. Tests add the ``job_try``
    that arq sets for each attempt with `_attempt`.
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

    ctx: dict[str, Any] = {
        "logger": logger,
        "process_context": process_context,
        "slack": AsyncMock(),
    }
    yield ctx

    await process_context.aclose()
    await db_session_dependency.aclose()


@pytest.fixture(autouse=True)
def _accept_fixture_org(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accept the owner of the repository in the webhook fixtures."""
    monkeypatch.setattr(config, "github_orgs", "Codertocat")


def _attempt(ctx: dict[str, Any], job_try: int) -> dict[str, Any]:
    """Get the ``ctx`` arq passes to a job on its given attempt."""
    return {**ctx, "job_try": job_try}


def _payload(
    *, action: str = "requested", head_branch: str | None = "changes"
) -> GitHubCheckSuiteEventWithNullableBranchModel:
    """Create a ``check_suite`` payload for `HEAD_SHA`."""
    data = json.loads((WEBHOOKS / "check_suite_completed.json").read_text())
    data["action"] = action
    data["check_suite"]["head_branch"] = head_branch
    return GitHubCheckSuiteEventWithNullableBranchModel.model_validate(data)


def _make_mock(**kwargs: Any) -> MockGitHubCheckRunAPI:
    """Create a mock GitHub API for a check of `HEAD_SHA`.

    An invalid sidecar fails the configs check, which ends a check suite's
    flow before the notebook check needs the repository or page services.
    """
    check_run = json.loads((WEBHOOKS / "check_run_created.json").read_text())[
        "check_run"
    ]
    return MockGitHubCheckRunAPI(
        check_run=check_run, sidecar_content="enabled: [", **kwargs
    )


def _stale_branch_head() -> MockGitHubCheckRunAPI:
    """Mock GitHub reading ``changes`` at its previous tip, as it can for a
    moment after `HEAD_SHA` was pushed on top of it.
    """
    return _make_mock(
        branches={"master": [BASE_SHA], "changes": [BASE_SHA]},
        unbranched_commits={HEAD_SHA: BASE_SHA},
    )


def _stale_new_branch() -> MockGitHubCheckRunAPI:
    """Mock GitHub not finding ``changes`` at all, as it can for a moment
    after the branch was created by pushing `HEAD_SHA`.
    """
    return _make_mock(
        branches={"master": [BASE_SHA]},
        unbranched_commits={HEAD_SHA: BASE_SHA},
    )


def _pushed() -> MockGitHubCheckRunAPI:
    """Mock GitHub once it shows `HEAD_SHA` as the head of ``changes``."""
    return _make_mock(
        branches={"master": [BASE_SHA], "changes": [HEAD_SHA, BASE_SHA]}
    )


def _serve_attempts(
    monkeypatch: pytest.MonkeyPatch, mocks: list[MockGitHubCheckRunAPI]
) -> None:
    """Make each attempt of a check run task read GitHub through the next of
    the given mocks.
    """
    remaining: Iterator[MockGitHubCheckRunAPI] = iter(mocks)

    async def create_github_check_run_service(
        self: WorkerFactory, *, installation_id: int
    ) -> GitHubCheckRunService:
        return GitHubCheckRunService(
            http_client=self.http_client,
            github_client=cast("GitHubAPI", next(remaining)),
            # The invalid sidecar of `_make_mock` ends the check before these
            # services are used.
            repo_service=cast("GitHubRepoService", None),
            page_service=cast("PageService", None),
            logger=self._logger,
        )

    monkeypatch.setattr(
        WorkerFactory,
        "create_github_check_run_service",
        create_github_check_run_service,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale",
    [_stale_branch_head, _stale_new_branch],
    ids=["branch-at-previous-tip", "branch-not-found"],
)
async def test_requested_check_suite_checked_on_retry(
    worker_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    stale: Callable[[], MockGitHubCheckRunAPI],
) -> None:
    """A requested check suite whose commit GitHub does not show on its
    branch yet is deferred without a Slack alert, and its check runs are
    created by the retry that finds the commit on its branch.
    """
    first, retry = stale(), _pushed()
    _serve_attempts(monkeypatch, [first, retry])

    with pytest.raises(Retry):
        await create_check_run(_attempt(worker_ctx, 1), payload=_payload())

    assert _write_requests(first) == []
    assert not _read_notebooks(first)
    worker_ctx["slack"].post.assert_not_called()

    result = await create_check_run(
        _attempt(worker_ctx, 2), payload=_payload()
    )

    assert result == "done"
    assert _created_check_runs(retry) == [
        GitHubConfigsCheck.title,
        NotebookExecutionsCheck.title,
    ]
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_requested_check_suite_skipped_after_bounded_retries(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A requested check suite whose commit GitHub never shows on its branch
    is skipped after the bounded retries: the last attempt ends without
    raising, and no attempt creates check runs or reads notebooks.
    """
    attempts = NOT_VISIBLE_RETRIES + 1
    mocks = [_stale_branch_head() for _ in range(attempts)]
    _serve_attempts(monkeypatch, mocks)

    for job_try in range(1, attempts):
        with pytest.raises(Retry):
            await create_check_run(
                _attempt(worker_ctx, job_try), payload=_payload()
            )
    result = await create_check_run(
        _attempt(worker_ctx, attempts), payload=_payload()
    )

    assert result == "done"
    for mock in mocks:
        assert _write_requests(mock) == []
        assert not _read_notebooks(mock)
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_requested_check_suite_retry_delays_increase(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each retry of a check suite whose commit GitHub does not show on its
    branch yet waits longer than the one before.
    """
    _serve_attempts(
        monkeypatch,
        [_stale_branch_head() for _ in range(NOT_VISIBLE_RETRIES)],
    )

    delays: list[int] = []
    for job_try in range(1, NOT_VISIBLE_RETRIES + 1):
        with pytest.raises(Retry) as excinfo:
            await create_check_run(
                _attempt(worker_ctx, job_try), payload=_payload()
            )
        assert excinfo.value.defer_score is not None
        delays.append(excinfo.value.defer_score)

    assert delays[0] > 0
    assert all(a < b for a, b in itertools.pairwise(delays))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "head_branch"),
    [("requested", None), ("rerequested", "changes")],
    ids=["null-head-branch", "rerequested-check-suite"],
)
async def test_check_suite_not_retried_when_lag_is_implausible(
    worker_ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    head_branch: str | None,
) -> None:
    """A check suite with no head branch, or a rerequested one, is skipped
    on its first attempt rather than retried, even when GitHub shows the
    branch at a parent of the commit.
    """
    mock = _stale_branch_head()
    _serve_attempts(monkeypatch, [mock])

    result = await create_check_run(
        _attempt(worker_ctx, 1),
        payload=_payload(action=action, head_branch=head_branch),
    )

    assert result == "done"
    assert _write_requests(mock) == []
    assert not _read_notebooks(mock)


@pytest.mark.asyncio
async def test_rerequested_check_run_not_retried(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-requested check run whose commit GitHub does not show on its
    branch is concluded as cancelled on its first attempt rather than
    retried.
    """
    mock = _make_mock(
        branches={"master": [BASE_SHA], "changes": [BASE_SHA]},
        unbranched_commits={HEAD_SHA: BASE_SHA},
        check_suite_head_branch="changes",
    )
    _serve_attempts(monkeypatch, [mock])
    data = json.loads((WEBHOOKS / "check_run_created.json").read_text())
    data["action"] = "rerequested"
    data["check_run"]["external_id"] = NotebookExecutionsCheck.external_id

    result = await create_rerequested_check_run(
        _attempt(worker_ctx, 1),
        payload=GitHubCheckRunEventModel.model_validate(data),
    )

    assert result == "done"
    assert [p["conclusion"] for p in mock.patched] == [
        GitHubCheckRunConclusion.cancelled
    ]
    assert not _read_notebooks(mock)


def _deferred_attempts(logs: Sequence[Mapping[str, Any]]) -> list[int]:
    """Get the attempt numbers of the logged deferrals."""
    return [entry["attempt"] for entry in logs if "defer_seconds" in entry]


def _final_outcomes(
    logs: Sequence[Mapping[str, Any]],
) -> list[tuple[int, str]]:
    """Get the attempt numbers and outcomes of the logged final outcomes."""
    return [
        (entry["attempt"], entry["outcome"])
        for entry in logs
        if "outcome" in entry
    ]


@pytest.mark.asyncio
async def test_rescued_check_suite_logs_attempts(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deferral, and the check that a retry rescues, are logged with their
    attempt numbers.
    """
    _serve_attempts(monkeypatch, [_stale_branch_head(), _pushed()])

    with capture_logs() as logs:
        with pytest.raises(Retry):
            await create_check_run(_attempt(worker_ctx, 1), payload=_payload())
        await create_check_run(_attempt(worker_ctx, 2), payload=_payload())

    assert _deferred_attempts(logs) == [1]
    assert _final_outcomes(logs) == [(2, CheckSuiteOutcome.checked)]


@pytest.mark.asyncio
async def test_exhausted_check_suite_logs_attempts(
    worker_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each deferral, and the skip once the retries run out, are logged with
    their attempt numbers.
    """
    attempts = NOT_VISIBLE_RETRIES + 1
    _serve_attempts(
        monkeypatch, [_stale_branch_head() for _ in range(attempts)]
    )

    with capture_logs() as logs:
        for job_try in range(1, attempts):
            with pytest.raises(Retry):
                await create_check_run(
                    _attempt(worker_ctx, job_try), payload=_payload()
                )
        await create_check_run(
            _attempt(worker_ctx, attempts), payload=_payload()
        )

    assert _deferred_attempts(logs) == list(range(1, attempts))
    assert _final_outcomes(logs) == [(attempts, CheckSuiteOutcome.skipped)]
