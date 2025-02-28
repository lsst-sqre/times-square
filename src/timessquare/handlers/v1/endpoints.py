"""Handler's for the /v1/."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import AnyHttpUrl
from safir.metadata import get_metadata
from safir.models import ErrorLocation, ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler
from sse_starlette import EventSourceResponse

from timessquare.config import config
from timessquare.dependencies.requestcontext import (
    RequestContext,
    context_dependency,
)
from timessquare.exceptions import (
    PageNotebookFormatError,
    PageNotFoundError,
    ParameterSchemaValidationError,
)

from ..apitags import ApiTags
from .models import (
    DeleteHtmlResponse,
    GitHubContentsRoot,
    GitHubPrContents,
    HtmlStatus,
    Index,
    Page,
    PageSummary,
    PostPageRequest,
)

__all__ = ["v1_router"]

v1_router = APIRouter(route_class=SlackRouteErrorHandler)
"""FastAPI router for all v1 handlers."""

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
    examples=["lsst-sqre/times-square-demo/matplotlib/gaussian2d"],
)

github_owner_parameter = Path(
    title="GitHub owner (organization or username)", examples=["lsst-sqre"]
)

github_repo_parameter = Path(
    title="GitHub repository", examples=["times-square-demo"]
)

page_path_parameter = Path(
    title="Page name",
    description=(
        "An opaque identifier for a page. This is often the 'name' field for "
        "a page's resource model."
    ),
    examples=["3d5a140634c34e249b7531667469b816"],
)

path_parameter = Path(
    title="Notebook path in repository (without extension)",
    examples=["matplotlib/gaussian2d"],
)

pr_commit_parameter = Path(
    title="Git commit for pull request check run",
    examples=["878092649b8bc1d8ef1436cc623bcecb923ece39"],
)


@v1_router.get(
    "/",
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
    return Index(
        metadata=metadata,
        api_docs=AnyHttpUrl(str(doc_url)),
    )


@v1_router.get(
    "/pages/{page}",
    summary="Page metadata",
    name="get_page",
    tags=[ApiTags.pages],
    responses={
        404: {"description": "Page not found", "model": ErrorModel},
    },
)
async def get_page(
    context: Annotated[RequestContext, Depends(context_dependency)],
    page: Annotated[str, page_path_parameter],
) -> Page:
    """Get metadata about a page resource, which models a webpage that is
    rendered from a parameterized Jupyter Notebook.
    """
    page_service = context.page_service
    async with context.session.begin():
        try:
            page_domain = await page_service.get_page(page)
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise

        context.response.headers["location"] = str(
            context.request.url_for("get_page", page=page_domain.name)
        )
        return Page.from_domain(page=page_domain, request=context.request)


@v1_router.get(
    "/pages",
    summary="List pages",
    name="get_pages",
    tags=[ApiTags.pages],
)
async def get_pages(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> list[PageSummary]:
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
    summary="Create a new page",
    status_code=201,
    tags=[ApiTags.pages],
    responses={
        422: {
            "description": "Invalid ipynb",
            "model": ErrorModel,
        },
    },
)
async def post_page(
    request_data: PostPageRequest,
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> Page:
    """Register a new page with a Jinja-templated Jupyter Notebook.

    ## Preparing the ipynb file

    The `ipynb` property is a Jupyter Notebook file, either as a JSON-encoded
    string or a parsed object. You can *parameterize* the notebook by
    adding Jinja template syntax. You can create Jinja variables that get
    their values from the URL query string of users viewing the notebook.

    For example, a code cell:

    ```
    a = {{params.a}}
    b = {{params.b}}
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
        try:
            page_exec = (
                await page_service.create_page_with_notebook_from_upload(
                    title=request_data.title,
                    ipynb=request_data.ipynb,
                    uploader_username=username,
                    authors=authors,
                    tags=request_data.tags,
                    description=request_data.description,
                    cache_ttl=request_data.cache_ttl,
                )
            )
        except PageNotebookFormatError as e:
            e.location = ErrorLocation.body
            e.field_path = ["ipynb"]
            raise
        page = await page_service.get_page(page_exec.page_name)

    context.response.headers["location"] = str(
        context.request.url_for("get_page", page=page_exec.page_name)
    )
    return Page.from_domain(page=page, request=context.request)


@v1_router.get(
    "/pages/{page}/source",
    summary="Get the source parameterized notebook (ipynb)",
    name="get_page_source",
    tags=[ApiTags.pages],
    responses={404: {"description": "Page not found", "model": ErrorModel}},
)
async def get_page_source(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> PlainTextResponse:
    """Get the content of the source ipynb file, which is unexecuted and has
    Jinja templating of parameterizations.
    """
    page_service = context.page_service
    async with context.session.begin():
        try:
            page_domain = await page_service.get_page(page)
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise

    response_headers = {
        "location": str(
            context.request.url_for("get_page_source", page=page_domain.name)
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
    tags=[ApiTags.pages],
    responses={
        404: {"description": "Page not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def get_rendered_notebook(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> PlainTextResponse:
    """Get a Jupyter Notebook by page slug, with the parameter values filled
    in. The notebook is still unexecuted.
    """
    page_service = context.page_service
    parameters = context.request.query_params
    async with context.session.begin():
        try:
            rendered_notebook = await page_service.render_page_template(
                page, parameters
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise
    return PlainTextResponse(rendered_notebook, media_type="application/json")


@v1_router.get(
    "/pages/{page}/html",
    summary="Get the HTML page of an computed notebook",
    name="get_page_html",
    tags=[ApiTags.pages],
    responses={
        200: {
            "description": "HTML of the notebook",
            "content": {"text/html": {}},
        },
        404: {"description": "Page not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def get_page_html(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> HTMLResponse:
    """Get the rendered HTML of a notebook."""
    page_service = context.page_service
    async with context.session.begin():
        try:
            html = await page_service.get_html(
                name=page, query_params=context.request.query_params
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise

    if not html:
        raise HTTPException(
            status_code=404, detail="Computing the notebook..."
        )

    return HTMLResponse(html.html)


@v1_router.delete(
    "/pages/{page}/html",
    summary="Delete the cached HTML of a notebook.",
    name="delete_page_html",
    tags=[ApiTags.pages],
    responses={
        404: {"description": "Cached HTML not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def delete_page_html(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> DeleteHtmlResponse:
    """Delete the cached HTML of a notebook execution, causing it to be
    recomputed in the background.

    By default, the HTML is soft-deleted so that it remains available to
    existing clients until the new HTML replaces it in the cache. This endpoint
    triggers a background task that recomputes the notebook and replaces the
    cached HTML.
    """
    page_service = context.page_service
    async with context.session.begin():
        try:
            page_instance = await page_service.soft_delete_html(
                name=page, query_params=context.request.query_params
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise

    # Ulimately create a resource that describes the background task;
    # or subscribe the client to a SSE stream that reports the task's progress.
    return DeleteHtmlResponse.from_page_instance(
        page_instance=page_instance, request=context.request
    )


@v1_router.get(
    "/pages/{page}/htmlstatus",
    summary="Get the status of a page's HTML rendering",
    name="get_page_html_status",
    tags=[ApiTags.pages],
    responses={
        404: {"description": "Page not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def get_page_html_status(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> HtmlStatus:
    page_service = context.page_service
    async with context.session.begin():
        try:
            html_status = await page_service.get_html_and_status(
                name=page, query_params=context.request.query_params
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise

    return HtmlStatus.from_html_status(
        html_status=html_status, request=context.request
    )


@v1_router.get(
    "/pages/{page}/html/events",
    summary=(
        "Subscribe to an event stream for a page's execution and rendering."
    ),
    name="get_page_html_events",
    tags=[ApiTags.pages],
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Event stream",
        },
        404: {"description": "Page not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def get_page_html_events(
    page: Annotated[str, page_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> EventSourceResponse:
    """Subscribe to an event stream for a page's execution and rendering."""
    context.logger.debug("Subscribing to page events")
    page_service = context.page_service
    html_base_url = context.request.url_for("get_page_html", page=page)
    async with context.session.begin():
        try:
            generator = await page_service.get_html_events_iter(
                name=page,
                query_params=context.request.query_params,
                html_base_url=str(html_base_url),
            )
            return EventSourceResponse(generator, send_timeout=5)
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise


@v1_router.get(
    "/github",
    summary="Get a tree of GitHub-backed pages",
    name="get_github_tree",
    tags=[ApiTags.github],
)
async def get_github_tree(
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> GitHubContentsRoot:
    """Get the tree of GitHub-backed pages.

    This endpoint is primarily intended to be used by Squareone to power
    its navigational view of GitHub pages. Pages are included in the
    hierarchical structure of GitHub organization, repository, directories
    (as necessary) and finally the page itself.
    """
    page_service = context.page_service
    async with context.session.begin():
        github_tree = await page_service.get_github_tree()
    return GitHubContentsRoot.from_tree(tree=github_tree)


@v1_router.get(
    "/github/rendered/{display_path:path}",
    summary=(
        "Get the unexecuted notebook source with rendered parameters for a "
        "GitHub-based notebook."
    ),
    name="get_github_rendered_notebook",
    tags=[ApiTags.github],
    responses={
        404: {"description": "Page not found", "model": ErrorModel},
        422: {"description": "Invalid parameter", "model": ErrorModel},
    },
)
async def get_github_rendered_notebook(
    display_path: Annotated[str, display_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> PlainTextResponse:
    """Get a Jupyter Notebook by GitHub path, with the parameter values filled
    in. The notebook is still unexecuted.

    This route provides the same functionality as ``get_rendered_notebook``,
    but exposed at a different path so that different access controls can be
    applied upstream.
    """
    page_service = context.page_service
    parameters = context.request.query_params
    async with context.session.begin():
        try:
            rendered_notebook = (
                await page_service.render_page_template_by_display_path(
                    display_path, parameters
                )
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise
        except ParameterSchemaValidationError as e:
            e.location = ErrorLocation.query
            e.field_path = [e.parameter]
            raise
    return PlainTextResponse(rendered_notebook, media_type="application/json")


@v1_router.get(
    "/github/{display_path:path}",
    summary="Metadata for GitHub-backed page",
    name="get_github_page",
    tags=[ApiTags.github],
    responses={404: {"description": "Page not found", "model": ErrorModel}},
)
async def get_github_page(
    display_path: Annotated[str, display_path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> Page:
    """Get the metadata for a GitHub-backed page.

    This endpoint provides the same data as ``GET /v1/pages/:page``, but
    is queried via the page's GitHub "display path" rather than the opaque
    page name.
    """
    page_service = context.page_service
    async with context.session.begin():
        try:
            page_domain = await page_service.get_github_backed_page(
                display_path
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["display_path"]
            raise

        context.response.headers["location"] = str(
            context.request.url_for("get_page", page=page_domain.name)
        )
        return Page.from_domain(page=page_domain, request=context.request)


@v1_router.get(
    "/github-pr/{owner}/{repo}/{commit}",
    summary="Get a tree of GitHub PR preview pages",
    name="get_github_pr_tree",
    tags=[ApiTags.pr],
)
async def get_github_pr_tree(
    owner: Annotated[str, github_owner_parameter],
    repo: Annotated[str, github_repo_parameter],
    commit: Annotated[str, pr_commit_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> GitHubPrContents:
    """Get the tree of GitHub-backed pages for a pull request.

    This endpoint is primarily intended to be used by Squareone to power
    its navigational view of GitHub pages for a specific pull request
    (actually a commit SHA) of a repository.
    """
    repo_service = await context.create_github_repo_service(
        owner=owner, repo=repo
    )  # consider handling response where the app is not installed
    page_service = repo_service.page_service

    async with context.session.begin():
        github_tree = await page_service.get_github_pr_tree(
            owner=owner, repo=repo, commit=commit
        )

    check_runs = await repo_service.get_check_runs(
        owner=owner, repo=repo, head_sha=commit
    )
    context.logger.debug(
        "Check runs",
        check_runs=[run.model_dump(mode="json") for run in check_runs],
    )

    pull_requests = await repo_service.get_pulls_for_check_runs(check_runs)
    context.logger.debug(
        "Pull requests",
        prs=[pr.model_dump(mode="json") for pr in pull_requests],
    )

    return GitHubPrContents.create(
        tree=github_tree,
        owner=owner,
        repo=repo,
        commit=commit,
        check_runs=check_runs,
        pull_requests=pull_requests,
    )


@v1_router.get(
    "/github-pr/{owner}/{repo}/{commit}/{path:path}",
    summary="Metadata for page in a pull request",
    name="get_github_pr_page",
    tags=[ApiTags.pr],
    responses={404: {"description": "Page not found", "model": ErrorModel}},
)
async def get_github_pr_page(
    owner: Annotated[str, github_owner_parameter],
    repo: Annotated[str, github_repo_parameter],
    commit: Annotated[str, pr_commit_parameter],
    path: Annotated[str, path_parameter],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> Page:
    """Get the metadata for a pull request preview of a GitHub-backed page."""
    page_service = context.page_service
    async with context.session.begin():
        try:
            page_domain = await page_service.get_github_pr_page(
                owner=owner,
                repo=repo,
                commit=commit,
                path=path,
            )
        except PageNotFoundError as e:
            e.location = ErrorLocation.path
            e.field_path = ["page"]
            raise

        context.response.headers["location"] = str(
            context.request.url_for("get_page", page=page_domain.name)
        )
        return Page.from_domain(page=page_domain, request=context.request)
