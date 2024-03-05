"""Models for the external handlers."""

from pydantic import AnyHttpUrl, BaseModel, Field
from safir.metadata import Metadata as SafirMetadata

__all__ = ["Index"]


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: SafirMetadata = Field(..., title="Package metadata")

    v1_api_base: AnyHttpUrl = Field(..., title="Base URL for the v1 REST API")

    api_docs: AnyHttpUrl = Field(..., title="API documentation URL")
