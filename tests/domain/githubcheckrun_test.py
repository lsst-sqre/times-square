"""Tests for the githubcheckrun domain.

Three areas are covered:

- graceful handling of transient GitHub errors during repository checkout;
- ingest-time validation of a notebook sidecar's run schedule by the configs
  check;
- the annotations and recorded execution status produced by
  `NotebookExecutionsCheck.report_noteburst_completion`, which derives both
  from the shared execution-outcome classifier
  (`timessquare.domain.executionoutcome`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from gidgethub.httpx import GitHubAPI
from safir.github.models import (
    GitHubCheckRunAnnotationLevel,
    GitHubCheckRunConclusion,
    GitHubCheckRunModel,
    GitHubRepositoryModel,
)
from safir.github.webhooks import GitHubCheckSuiteEventModel

from timessquare.domain.githubcheckrun import (
    SCHEDULE_EVALUATION_ERROR_TITLE,
    TRANSIENT_CHECKOUT_ERROR_MESSAGE,
    GitHubConfigsCheck,
    NotebookExecutionsCheck,
)
from timessquare.domain.page import PageExecutionInfo, PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.storage.github.retry import MAX_ATTEMPTS
from timessquare.storage.noteburst import (
    NotebookError,
    NoteburstErrorCodes,
    NoteburstExecutionError,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)

from ..support.github import MockGitHubCheckRunAPI
from ..support.noteburst import JOB_URL

DATA = Path(__file__).parent.joinpath("../data/github_webhooks")

ENQUEUE_TIME = datetime(2022, 3, 15, 4, 12, 0, tzinfo=UTC)
START_TIME = datetime(2022, 3, 15, 4, 13, 0, tzinfo=UTC)
FINISH_TIME = datetime(2022, 3, 15, 4, 13, 10, tzinfo=UTC)


def _load_check_suite() -> GitHubCheckSuiteEventModel:
    payload = json.loads((DATA / "check_suite_completed.json").read_text())
    return GitHubCheckSuiteEventModel.model_validate(payload)


def _load_check_run() -> dict:
    return json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instantaneous so tests do not actually wait."""
    monkeypatch.setattr(
        "timessquare.storage.github.retry._backoff_delay",
        lambda _attempt: 0.0,
    )


@pytest.mark.asyncio
async def test_validate_repo_concludes_on_transient_error() -> None:
    """A persistent transient checkout failure concludes the config check
    with a ``failure`` conclusion carrying the actionable re-run message,
    and no exception propagates.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        contents_error=httpx.ReadTimeout("slow"),
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    # The check concluded as a failure with the actionable message.
    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert any(
        a.message == TRANSIENT_CHECKOUT_ERROR_MESSAGE
        for a in check.annotations
    )

    # The times-square.yaml GET was retried up to the retry budget.
    contents_gets = [
        req
        for req in mock.requests
        if req[0] == "GET" and "times-square.yaml" in req[1]
    ]
    assert len(contents_gets) == MAX_ATTEMPTS

    # The final PATCH posted a failure conclusion to GitHub.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_repo_concludes_on_transient_tree_error() -> None:
    """A transient failure in the git tree read after a successful checkout
    also concludes the config check with a ``failure`` conclusion instead of
    leaving it dangling ``in_progress``.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        tree_error=httpx.ReadTimeout("slow"),
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    # The check concluded as a failure with the actionable message.
    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert any(
        a.message == TRANSIENT_CHECKOUT_ERROR_MESSAGE
        for a in check.annotations
    )

    # The tree GET was retried up to the retry budget.
    tree_gets = [
        req
        for req in mock.requests
        if req[0] == "GET" and "git/trees" in req[1]
    ]
    assert len(tree_gets) == MAX_ATTEMPTS

    # The final PATCH posted a failure conclusion to GitHub.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_repo_retries_transient_sidecar_error() -> None:
    """A transient failure fetching a notebook's sidecar blob is retried up to
    the retry budget before the config check concludes with a ``failure``.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        blob_error=httpx.ReadTimeout("slow"),
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    # The check concluded as a failure with the actionable message.
    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert any(
        a.message == TRANSIENT_CHECKOUT_ERROR_MESSAGE
        for a in check.annotations
    )

    # The sidecar blob GET was retried up to the retry budget.
    blob_gets = [
        req
        for req in mock.requests
        if req[0] == "GET" and "git/blobs" in req[1]
    ]
    assert len(blob_gets) == MAX_ATTEMPTS

    # The final PATCH posted a failure conclusion to GitHub.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_repo_propagates_non_transient_error() -> None:
    """A non-transient, unexpected error during checkout still propagates so
    the worker's Slack alert fires (behavior unchanged for real errors).
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        contents_error=RuntimeError("unexpected"),
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        await GitHubConfigsCheck.create_check_run_and_validate(
            github_client=cast("GitHubAPI", mock),
            repo=payload.repository,
            head_sha=payload.check_suite.head_sha,
        )


UNEVALUATABLE_SCHEDULE_SIDECAR = """
title: Broken schedule
schedule:
  - freq: monthly
    weekday: friday
    set_position: 0
"""
"""A sidecar that validates as YAML and against the sidecar schema, but whose
schedule rule serializes to an rruleset dateutil refuses to build
(``set_position`` is not range-checked by the sidecar schema).
"""

FROM_DATE_COUNT_SCHEDULE_SIDECAR = """
title: Counted schedule
schedule:
  - start: 2026-01-01T12:00:00Z
    freq: daily
    count: 5
"""
"""A legitimate from-date/``count`` schedule. Its serialized form carries
``"end": null``, which is the round-trip that used to break schedule
evaluation, so it must not produce an annotation.
"""


@pytest.mark.asyncio
async def test_validate_sidecar_annotates_unevaluatable_schedule() -> None:
    """A sidecar whose schedule cannot be evaluated fails the configs check
    with a failure annotation on the sidecar's path.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        sidecar_content=UNEVALUATABLE_SCHEDULE_SIDECAR,
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    schedule_annotations = [
        a
        for a in check.annotations
        if a.title == SCHEDULE_EVALUATION_ERROR_TITLE
    ]
    assert len(schedule_annotations) == 1
    annotation = schedule_annotations[0]
    assert annotation.path == "demo.yaml"
    assert annotation.annotation_level == GitHubCheckRunAnnotationLevel.failure
    # Assert on Times Square's own message, not on the underlying dateutil
    # error wording, which is not a stable contract. The trailing detail is
    # still checked for non-emptiness so the exception text keeps reaching
    # the annotation.
    message_prefix = (
        "Times Square could not compute the next run from this schedule: "
    )
    assert annotation.message.startswith(message_prefix)
    assert annotation.message.removeprefix(message_prefix).strip()

    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_sidecar_accepts_from_date_count_schedule() -> None:
    """A valid from-date/``count`` schedule passes the configs check with no
    annotation, so the ingest-time check raises no false failure.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        sidecar_content=FROM_DATE_COUNT_SCHEDULE_SIDECAR,
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    assert check.annotations == []
    assert check.conclusion == GitHubCheckRunConclusion.success
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.success


def _base_response(**kwargs: object) -> NoteburstJobResponseModel:
    data: dict[str, object] = {
        "self_url": JOB_URL,
        "enqueue_time": ENQUEUE_TIME,
        "status": NoteburstJobStatus.complete,
        "start_time": START_TIME,
        "finish_time": FINISH_TIME,
    }
    data.update(kwargs)
    return NoteburstJobResponseModel.model_validate(data)


def _make_check() -> NotebookExecutionsCheck:
    payload = json.loads((DATA / "check_run_created.json").read_text())
    check_run = GitHubCheckRunModel.model_validate(payload["check_run"])
    repo = GitHubRepositoryModel.model_validate(payload["repository"])
    return NotebookExecutionsCheck(check_run=check_run, repo=repo)


def _make_page_execution() -> PageExecutionInfo:
    page = PageModel(
        name="1",
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        date_deleted=None,
        github_owner="lsst-sqre",
        github_repo="times-square-demo",
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem="demo",
        repository_sidecar_extension=".yaml",
        repository_source_extension=".ipynb",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )
    return PageExecutionInfo(
        page=page,
        values={},
        noteburst_status_code=200,
    )


def test_report_completion_success() -> None:
    check = _make_check()
    job_result = _base_response(success=True, ipynb="{}")
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    # A successful execution adds no failure annotation.
    assert check.annotations == []
    assert len(check.notebook_executions) == 1
    assert check.notebook_executions[0].is_success is True


def test_report_completion_ipynb_error() -> None:
    check = _make_check()
    job_result = _base_response(
        success=True,
        ipynb="{}",
        ipynb_error=NotebookError(name="ValueError", message="boom"),
    )
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    assert len(check.annotations) == 1
    annotation = check.annotations[0]
    assert annotation.title == "Notebook exception: ValueError"
    assert annotation.message == "boom"
    assert annotation.annotation_level == GitHubCheckRunAnnotationLevel.failure
    # The notebook is renderable, but the cell error marks it unsuccessful.
    assert check.notebook_executions[0].is_success is False


def test_report_completion_timeout() -> None:
    check = _make_check()
    job_result = _base_response(
        success=False,
        ipynb=None,
        timeout=30.0,
        error=NoteburstExecutionError(code=NoteburstErrorCodes.timeout),
    )
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    annotation = check.annotations[0]
    assert annotation.title == "Notebook execution timeout"
    assert "timed out" in annotation.message
    assert "30" in annotation.message
    assert check.notebook_executions[0].is_success is False


def test_report_completion_jupyter_error() -> None:
    check = _make_check()
    job_result = _base_response(
        success=False,
        ipynb=None,
        error=NoteburstExecutionError(
            code=NoteburstErrorCodes.jupyter_error,
            message="kernel died",
        ),
    )
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    annotation = check.annotations[0]
    assert annotation.title == "Notebook execution error"
    assert "Jupyter" in annotation.message
    assert "kernel died" in annotation.message


def test_report_completion_unknown_error() -> None:
    check = _make_check()
    job_result = _base_response(
        success=False,
        ipynb=None,
        error=NoteburstExecutionError(
            code=NoteburstErrorCodes.unknown,
            message="something broke",
            exception_type="RuntimeError",
        ),
    )
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    annotation = check.annotations[0]
    assert annotation.title == "Notebook execution error"
    assert "system error" in annotation.message
    assert "RuntimeError" in annotation.message


def test_report_completion_no_error_field() -> None:
    check = _make_check()
    job_result = _base_response(success=False, ipynb=None)
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    annotation = check.annotations[0]
    assert annotation.title == "Notebook execution error"
    # Standardized wording from the shared formatter.
    assert "unknown reason" in annotation.message


def test_report_completion_result_unavailable() -> None:
    """An expired arq result (``success is None``) is a terminal execution
    failure annotated with the classifier's result-unavailable wording.
    """
    check = _make_check()
    job_result = _base_response(success=None, ipynb=None)
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    assert len(check.annotations) == 1
    annotation = check.annotations[0]
    assert annotation.title == "Notebook result unavailable"
    # Standardized wording from the shared formatter.
    assert "no longer available" in annotation.message
    assert annotation.annotation_level == GitHubCheckRunAnnotationLevel.failure
    assert check.notebook_executions[0].is_success is False


def test_report_completion_ipynb_error_with_success_false() -> None:
    """A notebook is present, so the outcome is renderable and the cell
    exception is annotated regardless of the ``success`` flag.
    """
    check = _make_check()
    job_result = _base_response(
        success=False,
        ipynb="{}",
        ipynb_error=NotebookError(name="ValueError", message="boom"),
    )
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    assert len(check.annotations) == 1
    annotation = check.annotations[0]
    assert annotation.title == "Notebook exception: ValueError"
    assert annotation.message == "boom"
    # The cell error makes the execution unsuccessful even though the
    # notebook itself is renderable.
    assert check.notebook_executions[0].is_success is False


def test_report_completion_renderable_with_success_false() -> None:
    """A notebook with no cell error is renderable and needs no annotation,
    even if the ``success`` flag disagrees.
    """
    check = _make_check()
    job_result = _base_response(success=False, ipynb="{}")
    check.report_noteburst_completion(
        page_execution=_make_page_execution(), job_result=job_result
    )
    assert check.annotations == []
    # Recorded success follows the classifier, so it agrees with the
    # annotation-free treatment above.
    assert check.notebook_executions[0].is_success is True


def test_report_completion_contract_violation() -> None:
    """A successful execution with no notebook violates Noteburst's contract
    and raises with the classifier's message.
    """
    check = _make_check()
    job_result = _base_response(success=True, ipynb=None)
    with pytest.raises(RuntimeError, match="did not return an executed"):
        check.report_noteburst_completion(
            page_execution=_make_page_execution(), job_result=job_result
        )
    # The execution is recorded as unsuccessful before the raise.
    assert check.notebook_executions[0].is_success is False
