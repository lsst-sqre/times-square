"""Domain model for a noteburst job (that corresponds to the execution of a
page's ipynb notebook for a given set of parameters.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import AnyHttpUrl, BaseModel


class NoteburstJobModel(BaseModel):
    """The domain model for a noteburst notebook execution job of a page's
    notebook.
    """

    date_submitted: datetime
    """The time when the execution job was submitted."""

    job_url: AnyHttpUrl
    """The URL of the noteburst job resource."""

    @classmethod
    def from_noteburst_response(
        cls, data: Mapping[str, Any]
    ) -> NoteburstJobModel:
        """Create a NoteburstJobModel from a noteburst job metadata
        response.
        """
        d = NoteburstJobResponseModel.parse_obj(data)
        return cls(
            date_submitted=d.enqueue_time,
            job_url=d.self_url,
        )


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

    ipynb: Optional[str] = None
    """The executed notebook."""

    start_time: Optional[datetime] = None
    """Time when the notebook execution started (only set if result is
    available).
    """

    finish_time: Optional[datetime] = None
    """Time when the notebook execution finished (only set if result is
    available).
    """

    success: Optional[bool] = None
    """Whether the execution was successful or not (only set if result is
    available).
    """
