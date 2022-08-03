"""Handler's for the /v1/."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from safir.metadata import get_metadata

from timessquare.config import config
from timessquare.dependencies.requestcontext import (
    RequestContext,
    context_dependency,
)

from .models import (
    GitHubTreeRoot,
    HtmlStatus,
    Index,
    Page,
    PageSummary,
    PostPageRequest,
)

__all__ = ["v1_router"]

v1_router = APIRouter(tags=["v1"])
"""FastAPI router for all external handlers."""

display_path_parameter = Path(
    title="Page display path",
    description=(
        "A display path is a POSIX-like '/'-separated path consisting "
        "of components:\n"
        "\n"
        "- GitHub owner (organization or username)\n"
        "- Github repository\n"
        "- Directory name or names (as appropriate)\n"
        "- Page filename stem\n"
    ),
    example="lsst-sqre/times-square-demo/matplotlib/gaussian2d",
)

page_path_parameter = Path(
    title="Page name",
    description=(
        "An opaque identifier for a page. This is often the 'name' field for "
        "a page's resource model."
    ),
    example="3d5a140634c34e249b7531667469b816",
)


@v1_router.get(
    "/",
    response_model=Index,
    summary="v1 API metadata",
)
async def get_index(
    request: Request,
) -> Index:
    """Get metadata about the v1 REST API, including links to documentation and
    endpoints.
    """
    metadata = get_metadata(
        package_name="times-square",
        application_name=config.name,
    )
    doc_url = request.url.replace(path=f"/{config.name}/docs")
    return Index(metadata=metadata, api_docs=str(doc_url))


@v1_router.get(
    "/pages/{page}",
    response_model=Page,
    summary="Page metadata",
    name="get_page",
)
async def get_page(
    page: str = page_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> Page:
    """Get metadata about a page resource, which models a webpage that is
    rendered from a parameterized Jupyter Notebook.
    """
    page_service = context.page_service
    async with context.session.begin():
        page_domain = await page_service.get_page(page)

        context.response.headers["location"] = context.request.url_for(
            "get_page", page=page_domain.name
        )
        return Page.from_domain(page=page_domain, request=context.request)


@v1_router.get(
    "/pages",
    response_model=List[PageSummary],
    summary="List pages",
    name="get_pages",
)
async def get_pages(
    context: RequestContext = Depends(context_dependency),
) -> List[PageSummary]:
    """List available pages."""
    page_service = context.page_service
    async with context.session.begin():
        page_summaries_domain = await page_service.get_page_summaries()
        return [
            PageSummary.from_domain(summary=s, request=context.request)
            for s in page_summaries_domain
        ]


@v1_router.post(
    "/pages",
    response_model=Page,
    summary="Create a new page",
    status_code=201,
)
async def post_page(
    request_data: PostPageRequest,
    context: RequestContext = Depends(context_dependency),
) -> Page:
    """Register a new page with a Jinja-templated Jupyter Notebook.

    ## Preparing the ipynb file

    The `ipynb` property is a Jupyter Notebook file, either as a JSON-encoded
    string or a parsed object. You can *parameterize* the notebook by
    adding Jinja template syntax. You can create Jinja variables that get
    their values from the URL query string of users viewing the notebook.

    For example, a code cell:

    ```
    a = {{ params.a }}
    b = {{ params.b }}
    a + b
    ```

    A viewer can set these parameters by modifying URLs query string:

    ```
    ?a=4&b=2
    ```

    To declare these parameters, add a `times-square` field to the notebook's
    metadata (top-level metadata, not per-cell metadata). This field should
    contain a ``parameters`` field that contains an object keyed by parameter
    name and the value is a
    [JSON Schema](https://json-schema.org/understanding-json-schema/) object
    describing that parameter. For example, to declare that parameters
    must be integers:

    ```json
    {
      "times-square": {
        "parameters": {
          "a": {
            "type": "integer",
            "default": 0,
            "description": "A demo value"
          },
          "b": {
            "type": "integer",
            "default": 0,
            "description": "Another demo value"
          }
        }
      }
    }
    ```

    These JSON Schema parameters have special use by Times Square beyond
    data validation:

    - ``default`` is used when the URL does not override a parameter value.
    - ``description`` is used for documentation.
    """
    page_service = context.page_service
    username = context.get_request_username()
    if username is None:
        raise HTTPException(
            status_code=500, detail="X-Auth-Request-User not set"
        )

    authors = [a.to_domain() for a in request_data.authors]

    async with context.session.begin():
        page_exec = await page_service.create_page_with_notebook_from_upload(
            title=request_data.title,
            ipynb=request_data.ipynb,
            uploader_username=username,
            authors=authors,
            tags=request_data.tags,
            description=request_data.description,
            cache_ttl=request_data.cache_ttl,
        )
        page = await page_service.get_page(page_exec.name)

    context.response.headers["location"] = context.request.url_for(
        "get_page", page=page_exec.name
    )
    return Page.from_domain(page=page, request=context.request)


@v1_router.get(
    "/pages/{page}/source",
    summary="Get the source parameterized notebook (ipynb)",
    name="get_page_source",
)
async def get_page_source(
    page: str = page_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> PlainTextResponse:
    """Get the content of the source ipynb file, which is unexecuted and has
    Jinja templating of parameterizations.
    """
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
    summary="Get the unexecuted notebook source with rendered parameters",
    name="get_rendered_notebook",
)
async def get_rendered_notebook(
    page: str = page_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> PlainTextResponse:
    """Get a Jupyter Notebook with the parameter values filled in. The
    notebook is still unexecuted.
    """
    page_service = context.page_service
    parameters = context.request.query_params
    async with context.session.begin():
        rendered_notebook = await page_service.render_page_template(
            page, parameters
        )
    return PlainTextResponse(rendered_notebook, media_type="application/json")


@v1_router.get(
    "/pages/{page}/html",
    summary="Get the HTML page of an computed notebook",
    name="get_page_html",
)
async def get_page_html(
    page: str = page_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> HTMLResponse:
    """Get the rendered HTML of a notebook."""
    page_service = context.page_service
    async with context.session.begin():
        html = await page_service.get_html(
            name=page, query_params=context.request.query_params
        )

    if not html:
        raise HTTPException(
            status_code=404, detail="Computing the notebook..."
        )

    return HTMLResponse(html.html)


@v1_router.get(
    "/pages/{page}/htmlstatus",
    summary="Get the status of a page's HTML rendering",
    name="get_page_html_status",
    response_model=HtmlStatus,
)
async def get_page_html_status(
    page: str = page_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> HtmlStatus:
    page_service = context.page_service
    async with context.session.begin():
        html = await page_service.get_html(
            name=page, query_params=context.request.query_params
        )

    return HtmlStatus.from_html(html=html, request=context.request)


@v1_router.get(
    "/github",
    summary="Get a tree of GitHub-backed pages",
    name="get_github_tree",
    response_model=GitHubTreeRoot,
)
async def get_github_tree(
    context: RequestContext = Depends(context_dependency),
) -> GitHubTreeRoot:
    """Get the tree of GitHub-backed pages.

    This endpoint is primarily intended to be used by Squareone to power
    its navigational view of GitHub pages. Pages are included in the
    hierarchical structure of GitHub organization, repository, directories
    (as necessary) and finally the page itself.
    """
    page_service = context.page_service
    async with context.session.begin():
        github_tree = await page_service.get_github_tree()
    return GitHubTreeRoot.from_tree(tree=github_tree)


@v1_router.get(
    "/github/{display_path:path}",
    response_model=Page,
    summary="Metadata for GitHub-backed page",
    name="get_github_page",
)
async def get_github_page(
    display_path: str = display_path_parameter,
    context: RequestContext = Depends(context_dependency),
) -> Page:
    """Get the metadata for a GitHub-backed page.

    This endpoint provides the same data as ``GET /v1/pages/:page``, but
    is queried via the page's GitHub "display path" rather than the opaque
    page name.
    """
    page_service = context.page_service
    async with context.session.begin():
        page_domain = await page_service.get_github_backed_page(display_path)

        context.response.headers["location"] = context.request.url_for(
            "get_page", page=page_domain.name
        )
        return Page.from_domain(page=page_domain, request=context.request)
