"""Handler's for the /v1/."""

from fastapi import APIRouter, Depends, HTTPException, Request
from safir.metadata import get_metadata

from timessquare.config import config
from timessquare.dependencies.requestcontext import (
    RequestContext,
    context_dependency,
)

from .models import Index, Page, PostPageRequest

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


@v1_router.get(
    "/pages/{page}",
    description=(
        "Get metadata about a page resource, which models a webpage that is "
        "rendered from a parameterized Jupyter Notebook."
    ),
    response_model=Page,
    summary="Page metadata.",
    name="get_page",
)
async def get_page(
    page: str, context: RequestContext = Depends(context_dependency)
) -> Page:
    page_service = context.page_service
    page_domain = await page_service.get_page(page)
    if page_domain is None:
        raise HTTPException(
            status_code=404, detail=f"Page {page} does not exist."
        )

    context.response.headers["location"] = context.request.url_for(
        "get_page", page=page_domain.name
    )
    return Page.from_domain(page=page_domain, request=context.request)


@v1_router.post(
    "/pages",
    description="Create a new page.",
    response_model=Page,
    summary="Create a new page.",
    status_code=201,
)
async def post_page(
    request_data: PostPageRequest,
    context: RequestContext = Depends(context_dependency),
) -> Page:
    page_service = context.page_service
    page_service.create_page_with_notebook(
        name=request_data.name, ipynb=request_data.ipynb
    )
    page = await page_service.get_page(request_data.name)
    if page is None:
        raise HTTPException(status_code=500, detail="Error creating page.")

    context.response.headers["location"] = context.request.url_for(
        "get_page", page=page.name
    )
    return Page.from_domain(page=page, request=context.request)
