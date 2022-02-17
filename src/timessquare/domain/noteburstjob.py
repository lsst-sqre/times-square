"""Domain model for a noteburst job (that corresponds to the execution of a
page's ipynb notebook for a given set of parameters.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from pydantic import AnyHttpUrl, BaseModel


class NoteburstJobModel(BaseModel):
    """The domain model for a noteburst notebook execution job of a page's
    notebook.
    """

    date_submitted: datetime
    """The time when the execution job was submitted."""

    job_url: AnyHttpUrl
    """The URL of the noteburst job's metadata record."""

    result_url: AnyHttpUrl
    """The URL of the noteburst result."""

    @classmethod
    def from_noteburst_response(
        cls, data: Mapping[str, Any]
    ) -> NoteburstJobModel:
        """Create a NoteburstJobModel from a noteburst job metadata
        response.
        """
        d = NoteburstJobMetadataResponseModel.parse_obj(data)
        return cls(
            date_submitted=d.enqueue_time,
            job_url=d.self_url,
            result_url=d.result_url,
        )


class NoteburstJobStatus(str, Enum):
    """Enum of noteburst job statuses."""

    deferred = "deferred"
    queued = "queued"
    in_progress = "in_progress"
    complete = "complete"
    not_found = "not_found"


class NoteburstJobMetadataResponseModel(BaseModel):
    """A model for a subset of the noteburst response body for job
    metadata.
    """

    enqueue_time: datetime
    """Time when the job was added to the queue (UTC)."""

    status: NoteburstJobStatus
    """The current status of the notebook execution job."""

    self_url: AnyHttpUrl
    """The URL of this resource."""

    result_url: AnyHttpUrl
    """The URL for the result."""


class NoteburstResultResponseModel(BaseModel):
    """A model for a subset of the noteburst response body for a job result."""

    ipynb: str
    """The executed notebook."""

    status: NoteburstJobStatus
    """The current status of the notebook execution job."""

    start_time: datetime
    """Time when the notebook execution started."""

    finish_time: datetime
    """Time when the notebook execution finished."""

    success: bool
    """Whether the execution was successful or not."""
