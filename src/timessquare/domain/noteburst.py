"""Domain model for the noteburst service integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from httpx import AsyncClient
from pydantic import AnyHttpUrl, BaseModel

from timessquare.config import config


class NoteburstJobModel(BaseModel):
    """The domain model for a noteburst notebook execution job of a page's
    notebook.
    """

    date_submitted: datetime
    """The time when the execution job was submitted."""

    job_url: AnyHttpUrl
    """The URL of the noteburst job resource."""


class NoteburstJobStatus(str, Enum):
    """Enum of noteburst job statuses."""

    deferred = "deferred"
    queued = "queued"
    in_progress = "in_progress"
    complete = "complete"
    not_found = "not_found"


class NoteburstJobResponseModel(BaseModel):
    """A model for a subset of the noteburst response body for a notebook
    execution request.
    """

    self_url: AnyHttpUrl
    """The URL of this resource."""

    enqueue_time: datetime
    """Time when the job was added to the queue (UTC)."""

    status: NoteburstJobStatus
    """The current status of the notebook execution job."""

    ipynb: str | None = None
    """The executed notebook."""

    start_time: datetime | None = None
    """Time when the notebook execution started (only set if result is
    available).
    """

    finish_time: datetime | None = None
    """Time when the notebook execution finished (only set if result is
    available).
    """

    success: bool | None = None
    """Whether the execution was successful or not (only set if result is
    available).
    """

    def to_job_model(self) -> NoteburstJobModel:
        """Export to a `NoteburstJobModel` for storage."""
        return NoteburstJobModel(
            date_submitted=self.enqueue_time, job_url=self.self_url
        )


@dataclass
class NoteburstApiResult:
    """A result from the noteburst API."""

    data: NoteburstJobResponseModel | None

    status_code: int

    error: str | None = None


class NoteburstApi:
    """A client for the noteburst noteburst execution service API."""

    def __init__(self, http_client: AsyncClient) -> None:
        self._http_client = http_client

    async def submit_job(
        self, *, ipynb: str, kernel: str = "LSST", enable_retry: bool = True
    ) -> NoteburstApiResult:
        base_url = str(config.environment_url).rstrip("/")
        r = await self._http_client.post(
            f"{base_url}/noteburst/v1/notebooks/",
            json={
                "ipynb": ipynb,
                "kernel_name": kernel,
                "enable_retry": enable_retry,
            },
            headers=self._noteburst_auth_header,
        )
        if r.status_code == 202:
            return NoteburstApiResult(
                status_code=r.status_code,
                data=NoteburstJobResponseModel.model_validate(r.json()),
                error=None,
            )
        else:
            return NoteburstApiResult(
                status_code=r.status_code, data=None, error=r.text
            )

    async def get_job(self, job_url: str) -> NoteburstApiResult:
        r = await self._http_client.get(
            job_url, headers=self._noteburst_auth_header
        )
        if r.status_code == 200:
            return NoteburstApiResult(
                status_code=r.status_code,
                data=NoteburstJobResponseModel.model_validate(r.json()),
                error=None,
            )
        else:
            return NoteburstApiResult(
                status_code=r.status_code, data=None, error=r.text
            )

    @property
    def _noteburst_auth_header(self) -> dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {config.gafaelfawr_token.get_secret_value()}"
            )
        }
