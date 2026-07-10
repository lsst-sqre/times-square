"""Tests for the notebook execution outcome classifier."""

from __future__ import annotations

from datetime import UTC, datetime

from timessquare.domain.executionoutcome import (
    ExecutionOutcomeKind,
    NotebookExecutionErrorCode,
    classify_noteburst_outcome,
)
from timessquare.storage.noteburst import (
    NotebookError,
    NoteburstErrorCodes,
    NoteburstExecutionError,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)

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


def test_renderable_success_with_ipynb() -> None:
    response = _base_response(success=True, ipynb="{}")
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.renderable
    assert outcome.failure is None


def test_renderable_success_with_ipynb_error() -> None:
    # A cell raised, but an executed notebook is still returned: renderable.
    response = _base_response(
        success=True,
        ipynb="{}",
        ipynb_error=NotebookError(name="ValueError", message="boom"),
    )
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.renderable
    assert outcome.failure is None


def test_execution_failure_timeout() -> None:
    response = _base_response(
        success=False,
        ipynb=None,
        timeout=30.0,
        error=NoteburstExecutionError(code=NoteburstErrorCodes.timeout),
    )
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.execution_failure
    assert outcome.failure is not None
    assert outcome.failure.code is NotebookExecutionErrorCode.timeout
    assert "timed out" in outcome.failure.message
    assert "30" in outcome.failure.message
    assert outcome.failure.title


def test_execution_failure_jupyter_error() -> None:
    response = _base_response(
        success=False,
        ipynb=None,
        error=NoteburstExecutionError(
            code=NoteburstErrorCodes.jupyter_error,
            message="kernel died",
        ),
    )
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.execution_failure
    assert outcome.failure is not None
    assert outcome.failure.code is NotebookExecutionErrorCode.jupyter_error
    assert "Jupyter" in outcome.failure.message
    assert "kernel died" in outcome.failure.message


def test_execution_failure_unknown() -> None:
    response = _base_response(
        success=False,
        ipynb=None,
        error=NoteburstExecutionError(
            code=NoteburstErrorCodes.unknown,
            message="something broke",
            exception_type="RuntimeError",
        ),
    )
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.execution_failure
    assert outcome.failure is not None
    assert outcome.failure.code is NotebookExecutionErrorCode.unknown
    assert "system error" in outcome.failure.message
    assert "RuntimeError" in outcome.failure.message


def test_execution_failure_no_error_field() -> None:
    # success is False but no error payload provided.
    response = _base_response(success=False, ipynb=None)
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.execution_failure
    assert outcome.failure is not None
    assert outcome.failure.code is NotebookExecutionErrorCode.unknown


def test_execution_failure_result_expiry() -> None:
    # success is None (arq result expiry) and no ipynb.
    response = _base_response(success=None, ipynb=None)
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.execution_failure
    assert outcome.failure is not None
    assert (
        outcome.failure.code is NotebookExecutionErrorCode.result_unavailable
    )
    assert outcome.failure.message


def test_contract_violation() -> None:
    # The genuinely impossible state: success True but no ipynb.
    response = _base_response(success=True, ipynb=None)
    outcome = classify_noteburst_outcome(response)
    assert outcome.kind is ExecutionOutcomeKind.contract_violation
    assert outcome.failure is None
    assert outcome.contract_violation_message
    assert "no ipynb" not in outcome.contract_violation_message
