"""Request and response models for the v1 API."""

from __future__ import annotations

from fastapi import Request
from pydantic import AnyHttpUrl, BaseModel, Field
from safir.metadata import Metadata as SafirMetadata

from timessquare.domain.page import PageModel


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

    @classmethod
    def from_domain(cls, *, page: PageModel, request: Request) -> Page:
        """Create a page resource from the domain model."""
        return cls(
            name=page.name,
            self_url=request.url_for("get_page", page=page.name),
        )


class PostPageRequest(BaseModel):
    """A payload for creating a new page."""

    name: str = page_name_field

    ipynb: str = ipynb_field
