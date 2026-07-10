"""Classifier for the outcome of a completed Noteburst execution.

This is the single source of truth for translating a completed
`~timessquare.storage.noteburst.NoteburstJobResponseModel` into one of three
outcomes:

- **renderable** — an executed notebook (``ipynb``) is present and can be
  rendered to HTML, whether or not a cell raised an exception
  (``ipynb_error``).
- **execution failure** — no executed notebook is present because the
  execution failed at the infrastructure level (``success is False`` with a
  populated ``error``) or the result is no longer available (``success is
  None`` from arq result expiry). Carries a machine-readable
  `NotebookExecutionErrorCode` plus a human-readable title and message.
- **contract violation** — ``success is True`` but no notebook was returned.
  This is genuinely impossible per Noteburst's contract and callers should
  raise.

The human-readable failure descriptions live here so the interactive API
error field, the SSE payload, the background/scheduled worker logs, and the
GitHub check-run annotations all describe a failure the same way and cannot
drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from ..storage.noteburst import (
    NotebookError,
    NoteburstErrorCodes,
    NoteburstJobResponseModel,
)

__all__ = [
    "ExecutionOutcomeKind",
    "NotebookExecutionErrorCode",
    "NotebookExecutionFailure",
    "NoteburstExecutionOutcome",
    "classify_noteburst_outcome",
]


class NotebookExecutionErrorCode(StrEnum):
    """Machine-readable codes for a terminal notebook execution failure.

    This is a Times Square-owned enum for the public API so that the API is
    not directly coupled to Noteburst's internal `NoteburstErrorCodes`. The
    first three values mirror `NoteburstErrorCodes`; ``result_unavailable``
    covers the arq result-expiry case where Noteburst no longer has a result.
    """

    timeout = "timeout"
    """The notebook execution timed out."""

    jupyter_error = "jupyter_error"
    """An error occurred contacting the Jupyter server."""

    unknown = "unknown"
    """An unexpected system error occurred during execution."""

    result_unavailable = "result_unavailable"
    """The execution result is no longer available (e.g. arq result expiry)."""


class NotebookExecutionFailure(BaseModel):
    """A terminal, user-facing description of a failed notebook execution.

    Instances are cached per page instance (see
    `~timessquare.storage.nbexecutionfailurestore.NbExecutionFailureStore`)
    and surfaced on the API as the ``execution_error`` field.
    """

    code: Annotated[
        NotebookExecutionErrorCode,
        Field(description="Machine-readable failure code."),
    ]

    title: Annotated[
        str,
        Field(description="A short, human-readable title for the failure."),
    ]

    message: Annotated[
        str,
        Field(description="A human-readable description of the failure."),
    ]

    ipynb_error: Annotated[
        NotebookError | None,
        Field(
            description=(
                "A cell-level error, if any. This is normally null on the "
                "terminal no-notebook failure path and is provided only for "
                "forward compatibility."
            )
        ),
    ] = None


class ExecutionOutcomeKind(StrEnum):
    """The kind of outcome for a completed Noteburst execution."""

    renderable = "renderable"
    """An executed notebook is available and can be rendered."""

    execution_failure = "execution_failure"
    """The notebook could not be executed; a terminal failure."""

    contract_violation = "contract_violation"
    """An impossible state that violates Noteburst's contract."""


@dataclass(frozen=True, kw_only=True)
class NoteburstExecutionOutcome:
    """The classified outcome of a completed Noteburst execution."""

    kind: ExecutionOutcomeKind
    """The kind of outcome."""

    failure: NotebookExecutionFailure | None = None
    """The failure description, set only when ``kind`` is
    `ExecutionOutcomeKind.execution_failure`.
    """

    contract_violation_message: str | None = None
    """An accurate error message, set only when ``kind`` is
    `ExecutionOutcomeKind.contract_violation`, for callers to raise with.
    """


def _describe_failure(
    response: NoteburstJobResponseModel,
) -> NotebookExecutionFailure:
    """Build a user-facing failure description from a completed response with
    no executed notebook.
    """
    if response.success is None:
        # arq result expiry: Noteburst finished the job but the result is no
        # longer retrievable.
        return NotebookExecutionFailure(
            code=NotebookExecutionErrorCode.result_unavailable,
            title="Notebook result unavailable",
            message=(
                "The notebook execution result is no longer available. "
                "Please re-run the notebook."
            ),
        )

    error = response.error
    if error is not None and error.code == NoteburstErrorCodes.timeout:
        if response.timeout:
            message = (
                "The notebook execution timed out "
                f"(timeout is {response.timeout:.0f} s)."
            )
        else:
            message = (
                "The notebook execution timed out "
                "but no timeout was specified."
            )
        return NotebookExecutionFailure(
            code=NotebookExecutionErrorCode.timeout,
            title="Notebook execution timeout",
            message=message,
        )

    if error is not None and error.code == NoteburstErrorCodes.jupyter_error:
        message = "The notebook execution failed because of a Jupyter error."
        if error.message:
            message += f" ({error.message})"
        return NotebookExecutionFailure(
            code=NotebookExecutionErrorCode.jupyter_error,
            title="Notebook execution error",
            message=message,
        )

    if error is not None and error.code == NoteburstErrorCodes.unknown:
        message = (
            "The notebook execution failed because of an unexpected "
            "system error."
        )
        if error.message:
            message += f" (exception: {error.exception_type}; {error.message})"
        return NotebookExecutionFailure(
            code=NotebookExecutionErrorCode.unknown,
            title="Notebook execution error",
            message=message,
        )

    # success is False but the error payload is missing or unrecognized.
    message = "The notebook execution failed for an unknown reason."
    if error is not None and error.message:
        message += f" ({error.message})"
    return NotebookExecutionFailure(
        code=NotebookExecutionErrorCode.unknown,
        title="Notebook execution error",
        message=message,
    )


def classify_noteburst_outcome(
    response: NoteburstJobResponseModel,
) -> NoteburstExecutionOutcome:
    """Classify a completed Noteburst execution into a renderable result, a
    terminal execution failure, or a contract violation.

    Parameters
    ----------
    response
        A completed Noteburst job response.

    Returns
    -------
    NoteburstExecutionOutcome
        The classified outcome. When ``kind`` is
        `ExecutionOutcomeKind.execution_failure`, ``failure`` carries the
        user-facing description. When ``kind`` is
        `ExecutionOutcomeKind.contract_violation`,
        ``contract_violation_message`` carries an accurate error message for
        the caller to raise with.
    """
    if response.ipynb is not None:
        return NoteburstExecutionOutcome(kind=ExecutionOutcomeKind.renderable)

    if response.success is True:
        return NoteburstExecutionOutcome(
            kind=ExecutionOutcomeKind.contract_violation,
            contract_violation_message=(
                "Noteburst reported a successful execution but did not "
                "return an executed notebook."
            ),
        )

    return NoteburstExecutionOutcome(
        kind=ExecutionOutcomeKind.execution_failure,
        failure=_describe_failure(response),
    )
