"""Domain model for an HTML-rendering of a notebook page."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping

from pydantic import BaseModel

from .noteburstjob import NoteburstResultResponseModel


class NbHtmlModel(BaseModel):
    """The domain model for an HTML-rendered notebook for a page.

    Instances of this model are typically stored in the Redis cache, see
    `timessquare.storage.nbhtmlcache.NbHtmlCacheStore`.
    """

    page_name: str
    """Name of the page (`timessquare.domain.page.PageModel`) that this
    html-rendering belongs to.
    """

    html: str
    """The HTML content."""

    parameters: Dict[str, Any]
    """The parameter values, keyed by parameter name.

    Values are native Python types (i.e., string values for parameters
    originally set in a URL query string have been converted into string,
    bool, int, or float Python types via
    `timessquare.domain.page.PageParameterSchema.cast_value`.
    """

    date_executed: datetime
    """The time when the notebook was executed (UTC)."""

    execution_duration: timedelta
    """The duration required to compute the notebook."""

    date_rendered: datetime
    """The time when the notebook was rendered to HTML (UTC)."""

    @classmethod
    def create_from_noteburst_result(
        cls,
        *,
        page_name: str,
        html: str,
        parameters: Mapping[str, Any],
        noteburst_result: NoteburstResultResponseModel,
    ) -> NbHtmlModel:
        td = noteburst_result.finish_time - noteburst_result.start_time
        return cls(
            page_name=page_name,
            html=html,
            parameters=dict(parameters),
            date_executed=noteburst_result.finish_time,
            date_rendered=datetime.utcnow(),
            execution_duration=td,
        )
