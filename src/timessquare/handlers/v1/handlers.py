"""Handler's for the /v1/."""

from fastapi import APIRouter
from safir.metadata import get_metadata
from starlette.requests import Request

from timessquare.config import config

from .models import Index

__all__ = ["v1_router"]

v1_router = APIRouter()
"""FastAPI router for all external handlers."""


@v1_router.get(
    "/",
    description=(
        "Metadata about the v1 REST API, including links to "
        "documentation and endpoints."
    ),
    response_model=Index,
    summary="V1 API metadata",
)
async def get_index(
    request: Request,
) -> Index:
    metadata = get_metadata(
        package_name="times-square",
        application_name=config.name,
    )
    return Index(metadata=metadata, api_docs=f"{request.url}docs")
