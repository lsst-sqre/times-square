"""Noteburst API test doubles."""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import Response

from timessquare.config import config

__all__ = [
    "JOB_ID",
    "JOB_URL",
    "NOTEBURST_URL",
    "queued_job_response",
]


NOTEBURST_URL = (
    f"{str(config.environment_url).rstrip('/')}/noteburst/v1/notebooks/"
)
"""The URL of Noteburst's notebook-execution endpoint.

Built the same way `~timessquare.storage.noteburst.NoteburstApi.submit_job`
builds it, so that a change to the path only has to be made in these two
places rather than in every test module that mocks Noteburst.
"""

JOB_ID = "xyz"
"""The job ID that `queued_job_response` reports."""

JOB_URL = f"{NOTEBURST_URL}{JOB_ID}"
"""The URL of the job resource that `queued_job_response` reports."""


def queued_job_response() -> Response:
    """Return the 202 response Noteburst sends for a newly queued job.

    Returns
    -------
    httpx.Response
        A 202 response whose body parses as a
        `~timessquare.storage.noteburst.NoteburstJobResponseModel` in the
        ``queued`` status, pointing at `JOB_URL`.
    """
    return Response(
        202,
        json={
            "job_id": JOB_ID,
            "kernel_name": "",
            "enqueue_time": datetime.now(tz=UTC).isoformat(),
            "status": "queued",
            "self_url": JOB_URL,
        },
    )
