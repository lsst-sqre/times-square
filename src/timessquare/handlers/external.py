"""Handlers for the app's external root, ``/timessquare/``."""

from fastapi import APIRouter, Depends
from pydantic import AnyHttpUrl, BaseModel, Field
from safir.dependencies.logger import logger_dependency
from safir.metadata import Metadata as SafirMetadata
from safir.metadata import get_metadata
from starlette.requests import Request
from structlog.stdlib import BoundLogger

from timessquare.config import config

__all__ = ["get_index", "external_router", "Index"]

external_router = APIRouter()
"""FastAPI router for all external handlers."""


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: SafirMetadata = Field(..., title="Package metadata")

    v1_api_base: AnyHttpUrl = Field(..., title="Base URL for the v1 REST API")

    api_docs: AnyHttpUrl = Field(..., tile="API documentation URL")


@external_router.get(
    "/",
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    request: Request,
    logger: BoundLogger = Depends(logger_dependency),
) -> Index:
    """GET metadata about the application."""
    # There is no need to log simple requests since uvicorn will do this
    # automatically, but this is included as an example of how to use the
    # logger for more complex logging.
    logger.info("Request for application metadata")

    metadata = get_metadata(
        package_name="times-square",
        application_name=config.name,
    )
    # Construct these URLs; this doesn't use request.url_for because the
    # endpoints are in other FastAPI "apps".
    v1_api_url = f"{request.url}v1"
    doc_url = request.url.replace(path=f"/{config.name}/redoc")
    return Index(
        metadata=metadata, v1_api_base=v1_api_url, api_docs=str(doc_url)
    )
