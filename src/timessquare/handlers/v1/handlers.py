"""Handler's for the /v1/."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
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
    doc_url = request.url.replace(path=f"/{config.name}/docs")
    return Index(metadata=metadata, api_docs=str(doc_url))


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
    async with context.session.begin():
        page_domain = await page_service.get_page(page)

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
    async with context.session.begin():
        page_service.create_page_with_notebook(
            name=request_data.name, ipynb=request_data.ipynb
        )
        page = await page_service.get_page(request_data.name)

        context.response.headers["location"] = context.request.url_for(
            "get_page", page=page.name
        )
        return Page.from_domain(page=page, request=context.request)


@v1_router.get(
    "/pages/{page}/source",
    description=(
        "Get the content of the source ipynb file, which is unexecuted and "
        "has Jinja templating of parameterizations."
    ),
    summary="Parameterized notebook source.",
    name="get_page_source",
)
async def get_page_source(
    page: str,
    context: RequestContext = Depends(context_dependency),
) -> PlainTextResponse:
    page_service = context.page_service
    async with context.session.begin():
        page_domain = await page_service.get_page(page)

        response_headers = {
            "location": context.request.url_for(
                "get_page_source", page=page_domain.name
            )
        }

        return PlainTextResponse(
            page_domain.ipynb,
            headers=response_headers,
            media_type="application/json",
        )


@v1_router.get(
    "/pages/{page}/rendered",
    description=(
        "Get a Jupyter Notebook with the parameter values filled in. The "
        "notebook is still unexecuted."
    ),
    summary="Unexecuted notebook source with parameters.",
    name="get_rendered_notebook",
)
async def get_rendered_notebook(
    page: str,
    context: RequestContext = Depends(context_dependency),
) -> PlainTextResponse:
    page_service = context.page_service
    parameters = context.request.query_params
    async with context.session.begin():
        rendered_notebook = await page_service.render_page_template(
            page, parameters
        )
        return PlainTextResponse(
            rendered_notebook, media_type="application/json"
        )


@v1_router.get(
    "/pages/{page}/html",
    description="Get the rendered HTML of a notebook.",
    summary="The HTML page of an computed notebook.",
    name="get_page_html",
)
async def get_page_html(
    page: str,
    context: RequestContext = Depends(context_dependency),
) -> HTMLResponse:
    page_service = context.page_service
    parameters = context.request.query_params
    async with context.session.begin():
        html = await page_service.get_html(name=page, parameters=parameters)

        if not html:
            raise HTTPException(status_code=404, detail="HTML not available")

        return HTMLResponse(html.html)
