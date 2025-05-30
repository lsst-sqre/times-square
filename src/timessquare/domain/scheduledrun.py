"""Domain model for a scheduled run of a page."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = ["ScheduledRun"]


class ScheduledRun(BaseModel):
    """A scheduled run of a page.

    Attributes
    ----------
    page_name
        The name of the page to be run.
    scheduled_time
        The time when the page is scheduled to be run.
    created_at
        The time when the scheduled run was created.
    """

    page_name: str = Field(..., description="Name of the page to be run")

    scheduled_time: datetime = Field(
        ..., description="Time when the page is scheduled to be run"
    )

    created_at: datetime = Field(
        ..., description="Time when the scheduled run was created"
    )

    job_id: str = Field(
        description="The job ID of the scheduled run in the task queue"
    )
