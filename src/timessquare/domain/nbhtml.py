"""Domain model for an HTML-rendering of a notebook page."""

from __future__ import annotations

import json
from base64 import b64encode
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any

from nbconvert.exporters.html import HTMLExporter
from pydantic import BaseModel, Field
from traitlets.config import Config

from ..storage.noteburst import NoteburstJobResponseModel
from .page import PageInstanceIdModel, PageInstanceModel


class NbHtmlModel(BaseModel):
    """The domain model for an HTML-rendered notebook for a page.

    Instances of this model are typically stored in the Redis cache, see
    `timessquare.storage.nbhtmlcache.NbHtmlCacheStore`.
    """

    page_name: Annotated[
        str,
        Field(
            description=(
                "Name of the page (`timessquare.domain.page.PageModel`) that "
                "this html-rendering belongs to."
            )
        ),
    ]

    html: Annotated[str, Field(description="The HTML content.")]

    html_hash: Annotated[
        str, Field(description="A sha256 hash of the HTML content.")
    ]

    values: Annotated[
        dict[str, Any],
        Field(
            description=(
                "The parameter values, keyed by parameter name. "
                "Values are native Python types (i.e., string values for "
                "parameters originally set in a URL query string have been "
                "converted into string, bool, int, or float Python types via "
                "`timessquare.domain.page.PageParameterSchema.cast_value`."
            )
        ),
    ]

    date_executed: Annotated[
        datetime,
        Field(description="The time when the notebook was executed (UTC)."),
    ]

    execution_duration: Annotated[
        timedelta,
        Field(description="The duration required to compute the notebook."),
    ]

    date_rendered: Annotated[
        datetime,
        Field(
            description=(
                "The time when the notebook was rendered to HTML (UTC)."
            )
        ),
    ]

    hide_code: Annotated[
        bool, Field(description="Whether the html includes code input cells.")
    ]

    @classmethod
    def create_from_noteburst_result(
        cls,
        *,
        page_instance: PageInstanceModel,
        ipynb: str,
        noteburst_result: NoteburstJobResponseModel,
        display_settings: NbDisplaySettings,
    ) -> NbHtmlModel:
        """Create an instance from a noteburst result."""
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
        if display_settings.hide_code:
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
            date_rendered=datetime.now(tz=UTC),
            execution_duration=td,
            hide_code=display_settings.hide_code,
        )

    def create_key(self) -> NbHtmlKey:
        """Create a storage key."""
        return NbHtmlKey(
            name=self.page_name,
            values=dict(self.values),
            display_settings=NbDisplaySettings(hide_code=self.hide_code),
        )


@dataclass
class NbHtmlKey(PageInstanceIdModel):
    """A domain model for the redis key for an NbHtmlModel instance."""

    display_settings: NbDisplaySettings

    @property
    def cache_key(self) -> str:
        key_prefix = super().cache_key
        return f"{key_prefix}/{self.display_settings.cache_key}"


@dataclass(frozen=True)
class NbDisplaySettings:
    """A model for display settings for an HTML rendering of a notebook."""

    hide_code: bool

    @property
    def cache_key(self) -> str:
        return b64encode(
            json.dumps(dict(asdict(self).items()), sort_keys=True).encode(
                "utf-8"
            )
        ).decode("utf-8")
