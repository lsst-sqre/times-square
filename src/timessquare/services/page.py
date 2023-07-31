"""The parmeterized notebook page service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.domain.githubtree import GitHubNode
from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey, NbHtmlModel
from timessquare.domain.noteburst import (
    NoteburstApi,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)
from timessquare.domain.page import (
    PageExecutionInfo,
    PageInstanceModel,
    PageModel,
    PageSummaryModel,
    PersonModel,
)
from timessquare.exceptions import PageNotFoundError
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore


class PageService:
    """A service manager for parameterized notebook pages.

    Parameters
    ----------
    page_store : `timessquare.storage.page.PageStore
        The PageStore, which adapts the database backend.
    logger : `structlog.stdlib.BoundLogger`
        The logger instance, bound with context about the request.
    """

    def __init__(
        self,
        page_store: PageStore,
        html_cache: NbHtmlCacheStore,
        job_store: NoteburstJobStore,
        http_client: AsyncClient,
        logger: BoundLogger,
    ) -> None:
        self._page_store = page_store
        self._html_store = html_cache
        self._job_store = job_store
        self._http_client = http_client
        self._logger = logger
        self.noteburst_api = NoteburstApi(http_client=http_client)

    async def create_page_with_notebook_from_upload(
        self,
        ipynb: str,
        title: str,
        uploader_username: str,
        description: str | None = None,
        cache_ttl: int | None = None,
        tags: list[str] | None = None,
        authors: list[PersonModel] | None = None,
    ) -> PageExecutionInfo:
        """Create a page resource given the parameterized Jupyter Notebook
        content.
        """
        page = PageModel.create_from_api_upload(
            title=title,
            ipynb=ipynb,
            uploader_username=uploader_username,
            description=description,
            cache_ttl=cache_ttl,
            tags=tags,
            authors=authors,
        )
        return await self.add_page_and_execute(page)

    async def add_page_to_store(self, page: PageModel) -> None:
        """Add a page to the page store.

        Parameters
        ----------
        page: `PageModel`
            The page model.

        Notes
        -----
        For API uploads, use `create_page_with_notebook_from_upload` instead.
        """
        self._page_store.add(page)

    async def add_page_and_execute(
        self, page: PageModel, *, enable_retry: bool = True
    ) -> PageExecutionInfo:
        """Add a page to the page store and execute it with defaults.

        Parameters
        ----------
        page: `PageModel`
            The page model.
        execute : `bool`
            Set this to `False` to disable the automatic noteburst execution
            of pages (useful for testing scenarios).

        Notes
        -----
        For API uploads, use `create_page_with_notebook_from_upload` instead.
        """
        await self.add_page_to_store(page)
        return await self.execute_page_with_defaults(
            page, enable_retry=enable_retry
        )

    async def get_page(self, name: str) -> PageModel:
        """Get the page from the data store, given its name."""
        page = await self._page_store.get(name)
        if page is None:
            raise PageNotFoundError(name)
        return page

    async def get_github_backed_page(self, display_path: str) -> PageModel:
        """Get the page based on its display path."""
        page = await self._page_store.get_github_backed_page(display_path)
        if page is None:
            raise PageNotFoundError(display_path)
        return page

    async def get_github_pr_page(
        self,
        *,
        owner: str,
        repo: str,
        commit: str,
        path: str,
    ) -> PageModel:
        """Get a page for a specific commit, corresponding to a GitHub PR's
        check run.

        Parameters
        ----------
        owner : `str`
            GitHub repository owner (username or organization).
        repo : `str`
            GitHub repository name.
        commit : `str`
            The SHA of the Git commit corresponding to the check run.
        path : `str`
            The page's path within the repository (without the file extension).

        Returns
        -------
        page : `PageModel`
            The domain model for a page. For PRs, this page is creating while
            processing the GitHub check suite.

        Raises
        ------
        PageNotFoundError
            Raised if the page is not found in the PageStore.
        """
        display_path = f"{owner}/{repo}/{path}"
        page = await self._page_store.get_github_backed_page(
            display_path, commit=commit
        )
        if page is None:
            # TODO add a commit attribute to the exception
            raise PageNotFoundError(display_path)
        return page

    async def get_page_summaries(self) -> list[PageSummaryModel]:
        """Get page summaries."""
        return await self._page_store.list_page_summaries()

    async def get_pages_for_repo(
        self, owner: str, name: str, commit: str | None = None
    ) -> list[PageModel]:
        """Get all pages backed by a specific GitHub repository."""
        return await self._page_store.list_pages_for_repository(
            owner=owner, name=name, commit=commit
        )

    async def get_github_tree(self) -> list[GitHubNode]:
        """Get the tree of GitHub-backed pages."""
        return await self._page_store.get_github_tree()

    async def get_github_pr_tree(
        self,
        *,
        owner: str,
        repo: str,
        commit: str,
    ) -> list[GitHubNode]:
        """Get the tree of GitHub-backed pages for a specific pull request."""
        return await self._page_store.get_github_pr_tree(
            owner=owner, repo=repo, commit=commit
        )

    async def update_page_in_store(self, page: PageModel) -> None:
        """Update the page in the database.

        Algorithm is:

        1. Update the page in Postgres
        2. Delete all cached HTML for the page from redis
        3. Execute the page with defaults
        """
        await self._page_store.update_page(page)
        await self._html_store.delete_objects_for_page(page.name)

    async def update_page_and_execute(
        self, page: PageModel, *, enable_retry: bool = True
    ) -> PageExecutionInfo:
        await self.update_page_in_store(page)
        return await self.execute_page_with_defaults(
            page, enable_retry=enable_retry
        )

    async def execute_page_with_defaults(
        self, page: PageModel, *, enable_retry: bool = True
    ) -> PageExecutionInfo:
        """Request noteburst execution of with page's default values.

        This is useful for the `add_page` and `update_page` methods to start
        notebook execution as soon as possible.
        """
        resolved_values = page.resolve_and_validate_values({})
        page_instance = PageInstanceModel(
            name=page.name, values=resolved_values, page=page
        )
        return await self.request_noteburst_execution(
            page_instance, enable_retry=enable_retry
        )

    async def soft_delete_page(self, page: PageModel) -> None:
        """Soft delete a page by setting its date_deleted field."""
        page.date_deleted = datetime.now(UTC)
        await self._page_store.update_page(page)

    async def soft_delete_pages_for_repo(self, owner: str, name: str) -> None:
        """Soft delete all pages backed by a specific GitHub repository."""
        for page in await self.get_pages_for_repo(owner=owner, name=name):
            await self.soft_delete_page(page)

    async def render_page_template(
        self, name: str, values: Mapping[str, Any]
    ) -> str:
        """Render a page's jupyter notebook, with the given parameter values.

        Parameters
        ----------
        name : `str`
            Name (URL slug) of the page.
        values : `dict`
            Parameter values, keyed by parameter names. If values are
            missing, the default value is used instead.
        """
        page = await self.get_page(name)
        resolved_values = page.resolve_and_validate_values(values)
        return page.render_parameters(resolved_values)

    async def get_html(
        self, *, name: str, query_params: Mapping[str, Any]
    ) -> NbHtmlModel | None:
        """Get the HTML for a page given the query parameters, first
        from a cache or triggering a rendering if not available.

        Returns
        -------
        nbhtml : `NbHtmlModel` or `None`
            The NbHtmlModel if available, or `None` if the executed notebook is
            not presently available.
        query_params
            The request query parameters, which contain parameter values as
            well as display settings.
        """
        # Get display settings from parameters
        try:
            hide_code = bool(int(query_params.get("ts_hide_code", "1")))
        except Exception as e:
            raise ValueError("hide_code query parameter must be 1 or 0") from e
        display_settings = NbDisplaySettings(hide_code=hide_code)
        self._logger.debug(
            "Resolved display settings",
            display_settings=asdict(display_settings),
        )

        page = await self.get_page(name)
        resolved_values = page.resolve_and_validate_values(query_params)

        # First try to get HTML from redis cache
        page_key = NbHtmlKey(
            name=page.name,
            values=resolved_values,
            display_settings=display_settings,
        )
        nbhtml = await self._html_store.get_instance(page_key)
        if nbhtml is not None:
            self._logger.debug("Got HTML from cache")
            return nbhtml

        # Second, look if there's an existing job request. If the job is
        # done this renders it into HTML; otherwise it triggers a noteburst
        # request, but does not return any HTML for this request.
        page_instance = PageInstanceModel(
            name=page.name, values=resolved_values, page=page
        )
        return await self._get_html_from_noteburst_job(
            page_instance=page_instance,
            display_settings=display_settings,
        )

    async def _get_html_from_noteburst_job(
        self,
        *,
        page_instance: PageInstanceModel,
        display_settings: NbDisplaySettings,
    ) -> NbHtmlModel | None:
        """Convert a noteburst job for a given page and parameter values into
        HTML (caching that HTML as well), and triggering a new noteburst.

        Parameters
        ----------
        page_instance : `PageInstanceModel`
            The page instance (consisting of resolved parameter values).
        display_settings : `NbDisplaySettings`
            A display parameter passed to `NbHtml.create_from_noteburst_result`
            that indicates whether the returned HTML should include code input
            cells.

        Returns
        -------
        nbhtml : `NbHtmlModel` or `None`
            The NbHtmlModel if available, or `None` if the executed notebook is
            not presently available.
        """
        # Is there an existing job in the noteburst job store?
        job = await self._job_store.get_instance(page_instance)
        if not job:
            self._logger.debug("No existing noteburst job available")
            # A record of a noteburst job is not available. Send a request
            # to noteburst.
            await self.request_noteburst_execution(page_instance)
            return None

        r = await self._http_client.get(
            job.job_url, headers=self._noteburst_auth_header
        )
        if r.status_code == 200:
            noteburst_response = NoteburstJobResponseModel.parse_obj(r.json())
            self._logger.debug(
                "Got noteburst job metadata",
                status=str(noteburst_response.status),
            )
            if noteburst_response.status == NoteburstJobStatus.complete:
                ipynb = noteburst_response.ipynb
                if ipynb is None:
                    raise RuntimeError(
                        "Noteburst job is complete but has no ipynb"
                    )
                html_renders = await self._create_html_matrix(
                    page_instance=page_instance,
                    ipynb=ipynb,
                    noteburst_response=noteburst_response,
                )
                # return the specific HTML render that the client asked for
                return html_renders[display_settings]

            else:
                # Noteburst job isn't complete
                return None

        elif r.status_code != 404:
            # Noteburst lost the job; delete our record and try again
            self._logger.warning(
                "Got a 404 from a noteburst job", job_url=job.job_url
            )
            await self._job_store.delete_instance(page_instance)
            await self.request_noteburst_execution(page_instance)
        else:
            # server error from noteburst
            self._logger.warning(
                "Got unknown response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
                noteburst_body=r.text,
            )
        return None

    async def request_noteburst_execution(
        self, page_instance: PageInstanceModel, *, enable_retry: bool = True
    ) -> PageExecutionInfo:
        """Request a notebook execution for a given page and parameters,
        and store the job.
        """
        ipynb = page_instance.page.render_parameters(page_instance.values)
        r = await self.noteburst_api.submit_job(
            ipynb=ipynb, enable_retry=enable_retry
        )
        if r.status_code != 202 or r.data is None:
            self._logger.warning(
                "Error requesting noteburst execution",
                noteburst_status=r.status_code,
                noteburst_body=r.error,
            )

            return PageExecutionInfo(
                name=page_instance.name,
                values=page_instance.values,
                page=page_instance.page,
                noteburst_job=None,
                noteburst_status_code=r.status_code,
                noteburst_error_message=r.error,
            )

        await self._job_store.store_job(
            job=r.data.to_job_model(), page_id=page_instance
        )
        self._logger.info(
            "Requested noteburst notebook execution",
            page_name=page_instance.name,
            parameters=page_instance.values,
            job_url=r.data.self_url,
        )
        if r.data is None:
            raise RuntimeError("Noteburst job has no data")
        return PageExecutionInfo(
            name=page_instance.name,
            values=page_instance.values,
            page=page_instance.page,
            noteburst_job=r.data.to_job_model(),
            noteburst_status_code=r.status_code,
            noteburst_error_message=r.error,
        )

    async def _create_html_matrix(
        self,
        *,
        page_instance: PageInstanceModel,
        ipynb: str,
        noteburst_response: NoteburstJobResponseModel,
    ) -> dict[Any, NbHtmlModel]:
        # These keys correspond to display arguments in
        # NbHtml.create_from_notebook_result
        matrix_keys = [
            NbDisplaySettings(hide_code=True),
            NbDisplaySettings(hide_code=False),
        ]
        html_matrix: dict[NbDisplaySettings, NbHtmlModel] = {}
        for matrix_key in matrix_keys:
            nbhtml = NbHtmlModel.create_from_noteburst_result(
                page_instance=page_instance,
                ipynb=ipynb,
                noteburst_result=noteburst_response,
                display_settings=matrix_key,
            )
            html_matrix[matrix_key] = nbhtml
            # TODO make lifetime a setting of page for pages that aren't
            # idempotent.
            await self._html_store.store_nbhtml(nbhtml=nbhtml, lifetime=None)
            self._logger.debug(
                "Stored new HTML", display_settings=asdict(matrix_key)
            )

        await self._job_store.delete_instance(page_instance)
        self._logger.debug("Deleted old job record")

        return html_matrix

    @property
    def _noteburst_auth_header(self) -> dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {config.gafaelfawr_token.get_secret_value()}"
            )
        }
