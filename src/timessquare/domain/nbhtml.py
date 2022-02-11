"""Domain model for an HTML-rendering of a notebook page."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel


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

    date_rendered: datetime
    """The time when the notebook was rendered to HTML (UTC)."""
