"""Request and response models for the v1 API."""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import Request
from pydantic import AnyHttpUrl, BaseModel, Field
from safir.metadata import Metadata as SafirMetadata

from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.page import PageModel, PageSummaryModel


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: SafirMetadata = Field(..., title="Package metadata")

    api_docs: AnyHttpUrl = Field(..., tile="Browsable API documentation")


page_name_field = Field(
    ...,
    example="summit-weather",
    title="Page name",
    description="The name is used as the page's URL slug.",
)

page_url_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather",
    title="Page resource URL.",
    description="API URL for the page's metadata resource.",
)

page_source_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/source",
    title="Source ipynb URL",
    description="The URL for the source ipynb file (JSON-formatted)",
)

page_parameters_field = Field(
    ...,
    example={"units": {"enum": ["metric", "imperial"], "default": "metric"}},
    title="Parameters",
    description="Parameters and their JSON Schema descriptions.",
)

page_rendered_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/rendered",
    title="Rendered notebook template URL",
    description=(
        "The URL for the source notebook rendered with parameter values "
        "(JSON-formatted)."
    ),
)

page_html_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/html",
    title="HTML view of computed notebook",
    description=(
        "The URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

page_html_status_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/htmlstatus",
    title="URL for the status of the HTML view of a notebook",
    description=(
        "The status URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

ipynb_field = Field(
    ...,
    example="{...}",
    title="ipynb",
    description="The JSON-encoded notebook content.",
)


class Page(BaseModel):
    """A webpage that is rendered from a parameterized notebook."""

    name: str = page_name_field

    self_url: AnyHttpUrl = page_url_field

    source_url: AnyHttpUrl = page_source_field

    rendered_url: AnyHttpUrl = page_rendered_field

    html_url: AnyHttpUrl = page_html_field

    html_status_url: AnyHttpUrl = page_html_status_field

    parameters: Dict[str, Dict[str, Any]] = page_parameters_field

    @classmethod
    def from_domain(cls, *, page: PageModel, request: Request) -> Page:
        """Create a page resource from the domain model."""
        parameters = {
            name: parameter.schema
            for name, parameter in page.parameters.items()
        }
        return cls(
            name=page.name,
            self_url=request.url_for("get_page", page=page.name),
            source_url=request.url_for("get_page_source", page=page.name),
            rendered_url=request.url_for(
                "get_rendered_notebook", page=page.name
            ),
            html_url=request.url_for("get_page_html", page=page.name),
            html_status_url=request.url_for(
                "get_page_html_status", page=page.name
            ),
            parameters=parameters,
        )


class PageSummary(BaseModel):
    """Summary information about a Page."""

    name: str = page_name_field

    self_url: AnyHttpUrl = page_url_field

    @classmethod
    def from_domain(
        cls, *, summary: PageSummaryModel, request: Request
    ) -> PageSummary:
        """Create a PageSummary response from the domain model."""
        return cls(
            name=summary.name,
            self_url=request.url_for("get_page", page=summary.name),
        )


class HtmlStatus(BaseModel):
    """Information about the availability of an HTML rendering for a given
    set of parameters.
    """

    available: bool = Field(
        ...,
        title="Html availability",
        description="If true, HTML is available in the cache for this set of "
        "parameters.",
    )

    html_url: AnyHttpUrl = page_html_field

    html_hash: Optional[str] = Field(
        ...,
        title="HTML content hash",
        description="A SHA256 hash of the HTML content. Clients can use this "
        "hash to determine if they are showing the current version of the "
        "HTML rendering. This field is null if the HTML is not available.",
    )

    @classmethod
    def from_html(
        cls, *, html: Optional[NbHtmlModel], request: Request
    ) -> HtmlStatus:
        base_html_url = request.url_for(
            "get_page_html", page=request.path_params["page"]
        )

        if html is None:
            # resolved parameters aren't available, so use the request URL
            qs = urlencode(request.query_params)
            if qs:
                html_url = f"{base_html_url}?{qs}"
            else:
                html_url = base_html_url

            return cls(available=False, html_url=html_url, html_hash=None)
        else:
            qs = urlencode(html.parameters)
            if qs:
                html_url = f"{base_html_url}?{qs}"
            else:
                html_url = base_html_url
            return cls(
                available=True, html_hash=html.html_hash, html_url=html_url
            )


class PostPageRequest(BaseModel):
    """A payload for creating a new page."""

    name: str = page_name_field

    ipynb: str = ipynb_field
