"""Tests for the notebook execution GitHub check-run domain model.

These are regression guards for the annotation text produced by
`NotebookExecutionsCheck.report_noteburst_completion`, which derives its
user-facing failure titles and messages from the shared execution-outcome
classifier (`timessquare.domain.executionoutcome`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from safir.github.models import (
    GitHubCheckRunAnnotationLevel,
    GitHubCheckRunModel,
    GitHubRepositoryModel,
)

from timessquare.domain.githubcheckrun import NotebookExecutionsCheck
from timessquare.domain.page import PageExecutionInfo, PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.storage.noteburst import (
    NotebookError,
    NoteburstErrorCodes,
    NoteburstExecutionError,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)

_WEBHOOK_DATA = Path(__file__).parent.parent / "data" / "github_webhooks"

SELF_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"
ENQUEUE_TIME = datetime(2022, 3, 15, 4, 12, 0, tzinfo=UTC)
START_TIME = datetime(2022, 3, 15, 4, 13, 0, tzinfo=UTC)
FINISH_TIME = datetime(2022, 3, 15, 4, 13, 10, tzinfo=UTC)


def _base_response(**kwargs: object) -> NoteburstJobResponseModel:
    data: dict[str, object] = {
        "self_url": SELF_URL,
        "enqueue_time": ENQUEUE_TIME,
        "status": NoteburstJobStatus.complete,
        "start_time": START_TIME,
        "finish_time": FINISH_TIME,
    }
    data.update(kwargs)
    return NoteburstJobResponseModel.model_validate(data)


def _make_check() -> NotebookExecutionsCheck:
    payload = json.loads(
        (_WEBHOOK_DATA / "check_run_created.json").read_text()
    )
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
