"""Domain model for an HTML-rendering of a notebook page."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Dict

from nbconvert.exporters.html import HTMLExporter
from pydantic import BaseModel
from traitlets.config import Config

from .noteburstjob import NoteburstJobResponseModel
from .page import PageInstanceModel


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

    html_hash: str
    """A sha256 hash of the HTML content."""

    values: Dict[str, Any]
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
        page_instance: PageInstanceModel,
        ipynb: str,
        noteburst_result: NoteburstJobResponseModel,
    ) -> NbHtmlModel:
        if not noteburst_result.start_time:
            raise RuntimeError(
                "Noteburst result does not include a start time"
            )
        if not noteburst_result.finish_time:
            raise RuntimeError(
                "Noteburst result does not include a finish time"
            )
        td = noteburst_result.finish_time - noteburst_result.start_time

        config = Config()
        config.HTMLExporter.exclude_input = True
        config.HTMLExporter.exclude_input_prompt = True
        config.HTMLExporter.exclude_output_prompt = True
        exporter = HTMLExporter(config=config)
        notebook = page_instance.page.read_ipynb(ipynb)
        html, resources = exporter.from_notebook_node(notebook)

        html_hash = sha256()
        html_hash.update(html.encode())

        return cls(
            page_name=page_instance.name,
            html=html,
            html_hash=html_hash.hexdigest(),
            values=page_instance.values,
            date_executed=noteburst_result.finish_time,
            date_rendered=datetime.utcnow(),
            execution_duration=td,
        )
