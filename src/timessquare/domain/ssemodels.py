"""Models for Server-Sent Events (SSE) endpoints.

Typically external models are maintained in the handlers subpackge, but
SSE emits data at a lower level so we provide a specific module for SSE
payload models that Times Square provides.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from pydantic import AnyHttpUrl, BaseModel, Field, field_serializer
from sse_starlette import ServerSentEvent

from timessquare.domain.page import PageInstanceModel

from ..storage.noteburst import NoteburstJobResponseModel, NoteburstJobStatus
from .nbhtml import NbHtmlKey, NbHtmlModel


class HtmlEventsModel(BaseModel):
    """Model for the notebook execution and HTML rendering events emitted by
    the SSE endpoint.
    """

    date_submitted: datetime | None = Field(
        ...,
        description=(
            "The time when the notebook execution job was submitted, or None "
            "if no job is ongoing."
        ),
    )

    date_started: datetime | None = Field(
        ...,
        description=(
            "The time when the notebook execution started, or None if no job "
            "is ongoing or the execution hasn't started yet."
        ),
    )

    date_finished: datetime | None = Field(
        ...,
        description=(
            "The time when the notebook execution finished, or None if no job "
            "is ongoing or the execution hasn't finished yet."
        ),
    )

    execution_status: NoteburstJobStatus | None = Field(
        ...,
        description=(
            "The status of the notebook execution job, or None if "
            "the notebook has not been queued to executed yet."
        ),
    )

    execution_duration: timedelta | None = Field(
        ...,
        description=(
            "The duration of the notebook execution in seconds, or None if no "
            "execution has completed."
        ),
    )

    html_hash: str | None = Field(
        ...,
        description=(
            "The sha256 hash of the HTML content, or None if no HTML is "
            "available."
        ),
    )

    html_url: AnyHttpUrl = Field(
        ...,
        description=(
            "The URL of the HTML content, or None if no HTML is available."
        ),
    )

    @field_serializer("execution_duration")
    def serialize_timedelta_seconds(
        self, td: timedelta | None
    ) -> float | None:
        if td:
            return td.total_seconds()
        return None

    @classmethod
    def create(
        cls,
        *,
        page_instance: PageInstanceModel,
        noteburst_job: NoteburstJobResponseModel | None,
        nbhtml: NbHtmlModel | None,
        html_base_url: str,
        request_query_params: Mapping[str, Any],
    ) -> HtmlEventsModel:
        """Create an instance from a ``NoteburstJobResponseModelModel`` and the
        Redis-cached ``NbHtmlModel`` (if available).
        """
        # Where dates are sourced from depends on whether the job is ongoing
        # in Noteburst or if it completed and the HTML was rendered.

        date_started: datetime | None = None
        date_submitted: datetime | None = None
        date_finished: datetime | None = None
        execution_status: NoteburstJobStatus | None = None
        execution_duration: timedelta | None = None
        html_hash: str | None = None

        if noteburst_job:
            # Execution is ongoing at Noteburst so derive dates from the job
            date_submitted = noteburst_job.enqueue_time
            date_started = noteburst_job.start_time
            date_finished = noteburst_job.finish_time
            execution_status = noteburst_job.status
            if (
                noteburst_job.status == NoteburstJobStatus.complete
                and noteburst_job.finish_time
                and noteburst_job.start_time
            ):
                execution_duration = (
                    noteburst_job.finish_time - noteburst_job.start_time
                )
            else:
                execution_duration = None
        elif nbhtml:
            # Execution has completed and the HTML is available
            date_started = nbhtml.date_executed - nbhtml.execution_duration
            date_submitted = date_started  # This is an approximation
            date_finished = nbhtml.date_executed
            execution_status = NoteburstJobStatus.complete
            execution_duration = nbhtml.execution_duration

        if nbhtml:
            nb_html_key = NbHtmlKey(
                name=page_instance.page_name,
                parameter_values=page_instance.id.parameter_values,
                display_settings=nbhtml.display_settings,
            )
            qs = nb_html_key.url_query_string
            html_url = AnyHttpUrl(f"{html_base_url}?{qs}")
            html_hash = nbhtml.html_hash
        elif noteburst_job:
            # If there isn't any HTML already, then we can't use the resolved
            # values from NbHtmlModel, so we use the query string from the
            # initial request instead
            qs = urlencode(request_query_params)
            html_url = AnyHttpUrl(f"{html_base_url}?{qs}")
        else:
            html_url = AnyHttpUrl(html_base_url)

        return cls(
            date_submitted=date_submitted,
            date_started=date_started,
            date_finished=date_finished,
            execution_status=execution_status,
            execution_duration=execution_duration,
            html_hash=html_hash,
            html_url=html_url,
        )

    def to_sse(self) -> ServerSentEvent:
        """Serialize the model to a ServerSentEvent."""
        return ServerSentEvent(self.model_dump_json())
