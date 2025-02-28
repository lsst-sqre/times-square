"""The parmeterized notebook page service."""

from __future__ import annotations

import asyncio
import json
from base64 import b64decode
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from safir.arq import ArqQueue
from structlog.stdlib import BoundLogger

from ..domain.githubtree import GitHubNode
from ..domain.nbhtml import (
    NbDisplaySettings,
    NbHtmlKey,
    NbHtmlModel,
    NbHtmlStatusModel,
)
from ..domain.page import (
    PageExecutionInfo,
    PageInstanceModel,
    PageModel,
    PageSummaryModel,
    PersonModel,
)
from ..domain.ssemodels import HtmlEventsModel
from ..exceptions import PageNotFoundError
from ..storage.nbhtmlcache import NbHtmlCacheStore
from ..storage.noteburst import (
    NoteburstApi,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)
from ..storage.noteburstjobstore import NoteburstJobStore
from ..storage.page import PageStore


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
        arq_queue: ArqQueue,
    ) -> None:
        self._page_store = page_store
        self._html_store = html_cache
        self._job_store = job_store
        self._http_client = http_client
        self._logger = logger
        self._arq_queue = arq_queue
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
            raise PageNotFoundError.for_page_id(name)
        return page

    async def get_github_backed_page(self, display_path: str) -> PageModel:
        """Get the page based on its display path."""
        page = await self._page_store.get_github_backed_page(display_path)
        if page is None:
            raise PageNotFoundError.for_page_id(display_path)
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
            raise PageNotFoundError.for_page_id(display_path)
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
        page_instance = PageInstanceModel(page=page, values={})
        return await self.request_noteburst_execution(
            page_instance, enable_retry=enable_retry
        )

    async def soft_delete_page(self, page: PageModel) -> None:
        """Soft delete a page by setting its date_deleted field."""
        page.date_deleted = datetime.now(UTC)
        await self.update_page_in_store(page)

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
        name
            Name (URL slug) of the page.
        values
            Parameter values, keyed by parameter names. If values are
            missing, the default value is used instead.
        """
        page = await self.get_page(name)
        page_instance = PageInstanceModel(page=page, values=dict(values))
        return page_instance.render_ipynb()

    async def render_page_template_by_display_path(
        self, display_path: str, values: Mapping[str, Any]
    ) -> str:
        """Render a GitHub-backed jupyter notebook, with the given parameter
        values.

        Parameters
        ----------
        display_path
            The path to the notebook in a GitHub URL.
        values
            Parameter values, keyed by parameter names. If values are
            missing, the default value is used instead.
        """
        page = await self.get_github_backed_page(display_path)
        page_instance = PageInstanceModel(page=page, values=dict(values))
        return page_instance.render_ipynb()

    async def get_html_and_status(
        self, *, name: str, query_params: Mapping[str, Any]
    ) -> NbHtmlStatusModel:
        """Get the status of the HTML rendering for a page, and the HTML itself
        if available.

        This method will get the HTML from the Redis cache, or alternatively
        check if there a noteburst job for this page instance and get the
        HTML from the job if it's available.

        Parameters
        ----------
        name
            The name of the page (slug in the pages API).
        query_params
            The URL query parameters for the page instance, comprising both
            parameter values and display settings.

        Returns
        -------
        nbhtml_status
            The status of the HTML rendering for the page and the HTML itself
            if available.
        """
        # Get display settings from parameters
        display_settings = NbDisplaySettings.from_url_params(query_params)
        self._logger.debug(
            "Resolved display settings",
            display_settings=asdict(display_settings),
        )

        page = await self.get_page(name)
        page_instance = PageInstanceModel(page=page, values=dict(query_params))

        # Get HTML from redis cache
        html_key = NbHtmlKey(
            display_settings=display_settings,
            page_instance_id=page_instance.id,
        )
        nbhtml = await self._html_store.get_instance(html_key)

        # Alternatively, look if there's an existing job request. If the job is
        # done this renders it into HTML; otherwise it triggers a noteburst
        # request, but does not return any HTML for this request.
        #
        # The fact that the UI periodically calls this service is what triggers
        # the rendering of the HTML after an execution by retrieving the
        # noteburst job.
        if nbhtml is None:
            nbhtml = await self._get_html_from_noteburst_job(
                page_instance=page_instance,
                display_settings=html_key.display_settings,
            )

        return NbHtmlStatusModel(
            nb_html=nbhtml, nb_html_key=html_key, page_instance=page_instance
        )

    async def get_html(
        self, *, name: str, query_params: Mapping[str, Any]
    ) -> NbHtmlModel | None:
        """Get the HTML for a page given the query parameters, first
        from a cache or triggering a rendering if not available.

        Parameters
        ----------
        name
            The name of the page (slug in the pages API).
        query_params
            The URL query parameters for the page instance, comprising both
            parameter values and display settings.

        Returns
        -------
        nbhtml | None
            The NbHtmlModel if available, or `None` if the executed notebook is
            not presently available.
        """
        html_status = await self.get_html_and_status(
            name=name, query_params=query_params
        )
        return html_status.nb_html

    async def _get_html_from_noteburst_job(
        self,
        *,
        page_instance: PageInstanceModel,
        display_settings: NbDisplaySettings,
    ) -> NbHtmlModel | None:
        """Convert a noteburst job for a given page and parameter values into
        HTML (caching that HTML as well), and triggering a new noteburst job if
        the job was not found.

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
        job = await self._job_store.get_instance(page_instance.id)
        if not job:
            self._logger.debug("No existing noteburst job available")
            # A record of a noteburst job is not available. Send a request
            # to noteburst.
            await self.request_noteburst_execution(page_instance)
            return None

        r = await self.noteburst_api.get_job(str(job.job_url))

        if r.status_code == 404:
            # Noteburst lost the job; delete our record and try again
            self._logger.warning(
                "Got a 404 from a noteburst job", job_url=job.job_url
            )
            await self._job_store.delete_instance(page_instance.id)
            await self.request_noteburst_execution(page_instance)
            return None

        elif r.status_code >= 500:
            # server error from noteburst
            self._logger.warning(
                "Got unknown response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
            )
            return None
        elif r.data is None:
            self._logger.warning(
                "Got empty response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
            )
            return None

        if r.data.status == NoteburstJobStatus.complete:
            html_renders = (
                await self.render_nbhtml_matrix_from_noteburst_response(
                    page_instance=page_instance,
                    noteburst_response=r.data,
                )
            )
            # return the specific HTML render that the client asked for
            return html_renders[display_settings]

        else:
            # Noteburst job isn't complete
            return None

    async def soft_delete_html(
        self, *, name: str, query_params: Mapping[str, Any]
    ) -> PageInstanceModel:
        """Soft delete the HTML for a page given the query parameters."""
        page = await self.get_page(name)
        page_instance = PageInstanceModel(page=page, values=dict(query_params))
        exec_info = await self.request_noteburst_execution(page_instance)
        await self._arq_queue.enqueue(  # provides an arq job metadata
            "replace_nbhtml",
            page_name=page.name,
            parameter_values=page_instance.values,
            noteburst_job=exec_info.noteburst_job,
        )
        # Format the job for a response
        return page_instance

    async def request_noteburst_execution(
        self, page_instance: PageInstanceModel, *, enable_retry: bool = True
    ) -> PageExecutionInfo:
        """Request a notebook execution for a given page and parameters,
        and store the job.
        """
        ipynb = page_instance.render_ipynb()
        r = await self.noteburst_api.submit_job(
            ipynb=ipynb,
            enable_retry=enable_retry,
            timeout=page_instance.page.execution_timeout,
        )
        if r.status_code != 202 or r.data is None:
            self._logger.warning(
                "Error requesting noteburst execution",
                noteburst_status=r.status_code,
                noteburst_body=r.error,
            )

            return PageExecutionInfo(
                values=page_instance.values,
                page=page_instance.page,
                noteburst_job=None,
                noteburst_status_code=r.status_code,
                noteburst_error_message=r.error,
            )

        await self._job_store.store_job(
            job=r.data.to_job_model(), page_id=page_instance.id
        )
        self._logger.info(
            "Requested noteburst notebook execution",
            page_name=page_instance.page_name,
            parameters=page_instance.values,
            job_url=r.data.self_url,
        )
        if r.data is None:
            raise RuntimeError("Noteburst job has no data")
        return PageExecutionInfo(
            values=page_instance.values,
            page=page_instance.page,
            noteburst_job=r.data.to_job_model(),
            noteburst_status_code=r.status_code,
            noteburst_error_message=r.error,
        )

    async def render_nbhtml_matrix_from_noteburst_response(
        self,
        *,
        page_instance: PageInstanceModel,
        noteburst_response: NoteburstJobResponseModel,
    ) -> dict[NbDisplaySettings, NbHtmlModel]:
        """Render the HTML matrix from a noteburst response.

        The Noteburst Job in the NoteburstJobStore is deleted after rendering.
        If the noteburst job did not appear in the store (because the HTML
        was being re-rendered in the background), this method still succeeds.
        """
        html_matrix: dict[NbDisplaySettings, NbHtmlModel] = {}
        if noteburst_response.ipynb is None:
            raise RuntimeError("Noteburst job is complete but has no ipynb")
        for matrix_key in NbDisplaySettings.create_settings_matrix():
            nbhtml = NbHtmlModel.create_from_noteburst_result(
                page_instance=page_instance,
                ipynb=noteburst_response.ipynb,
                noteburst_result=noteburst_response,
                display_settings=matrix_key,
            )
            html_matrix[matrix_key] = nbhtml
            html_key = NbHtmlKey(
                display_settings=matrix_key,
                page_instance_id=page_instance.id,
            )
            await self._html_store.store_nbhtml(
                key=html_key, nbhtml=nbhtml, lifetime=None
            )
            self._logger.debug(
                "Stored new HTML", display_settings=asdict(matrix_key)
            )

        deleted_job = await self._job_store.delete_instance(page_instance.id)
        if deleted_job:
            self._logger.debug("Deleted old job record")

        return html_matrix

    async def get_html_events_iter(
        self,
        name: str,
        query_params: Mapping[str, Any],
        html_base_url: str,
    ) -> AsyncIterator[bytes]:
        """Get an iterator providing an event stream for the HTML rendering
        for a page instance.
        """
        page = await self.get_page(name)
        page_instance = PageInstanceModel(page=page, values=dict(query_params))
        # also get the Display settings query params
        display_settings = NbDisplaySettings.from_url_params(query_params)
        html_key = NbHtmlKey(
            display_settings=display_settings,
            page_instance_id=page_instance.id,
        )

        async def iterator() -> AsyncIterator[bytes]:
            try:
                while True:
                    job = await self._job_store.get_instance(page_instance.id)
                    noteburst_data: NoteburstJobResponseModel | None = None
                    # model for html status
                    if job:
                        self._logger.debug(
                            "Got job in events loop", job_url=str(job.job_url)
                        )
                        noteburst_url = str(job.job_url)
                        noteburst_response = await self.noteburst_api.get_job(
                            noteburst_url
                        )
                        if noteburst_response.data:
                            noteburst_data = noteburst_response.data

                    nbhtml = await self._html_store.get_instance(html_key)

                    payload = HtmlEventsModel.create(
                        page_instance=page_instance,
                        noteburst_job=noteburst_data,
                        nbhtml=nbhtml,
                        request_query_params=query_params,
                        html_base_url=html_base_url,
                    )
                    self._logger.debug(
                        "Built payload in events loop", payload=payload
                    )
                    yield payload.to_sse().encode()

                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                self._logger.debug("HTML events disconnected from client")
                # cleanup as necessary
                raise
            except Exception as e:
                self._logger.exception("Error in HTML events iterator", e=e)
                raise

        return iterator()

    async def migrate_html_cache_keys(
        self, *, dry_run: bool = True, for_page_id: str | None = None
    ) -> int:
        """Migrate Redis keys to the new format.

        Parameters
        ----------
        dry_run
            If `True`, don't actually migrate the keys, but log what would be
            done.
        for_page_id
            If set, only migrate keys for the given page ID.

        Returns
        -------
        key_count
            The number of keys that were migrated (or would be migrated,
            if in dry-run).
        """
        key_count = 0
        if for_page_id:
            key_count += await self._migrate_html_cache_keys_for_page(
                dry_run=dry_run, page_id=for_page_id
            )
            return key_count

        for page_id in await self._page_store.list_page_names():
            key_count += await self._migrate_html_cache_keys_for_page(
                dry_run=dry_run, page_id=page_id
            )

        return key_count

    async def _migrate_html_cache_keys_for_page(
        self, *, dry_run: bool = True, page_id: str
    ) -> int:
        """Migrate the HTML cache keys for a specific page."""
        key_count = 0
        try:
            page = await self.get_page(page_id)
        except Exception as e:
            self._logger.warning(
                "Skipping page with error", page_id=page_id, error=str(e)
            )
            return key_count
        existing_keys = await self._html_store.list_keys_for_page(page.name)
        for existing_key in existing_keys:
            key_components = existing_key.split("/")
            if len(key_components) != 3:
                self._logger.warning(
                    "Skipping key with unexpected format",
                    key=existing_key,
                )
                continue
            if key_components[0] != page_id:
                self._logger.warning(
                    "Skipping key with unexpected page ID",
                    key=existing_key,
                    expected_page_id=page_id,
                )
                continue
            try:
                page_instance_values = json.loads(
                    b64decode(key_components[1]).decode("utf-8")
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid parameter values",
                    key=existing_key,
                    error=str(e),
                )
                continue
            try:
                display_settings_values = json.loads(
                    b64decode(key_components[2]).decode("utf-8")
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid display settings",
                    key=existing_key,
                    error=str(e),
                )
                continue

            try:
                page_instance = PageInstanceModel(
                    page=page, values=page_instance_values
                )
                page_instance_id = page_instance.id
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid page instance values",
                    key=existing_key,
                    error=str(e),
                )
                continue
            try:
                display_settings = NbDisplaySettings(
                    hide_code=(
                        display_settings_values.get("ts_hide_code", 1) == 1
                    )
                )
                nb_html_key = NbHtmlKey(
                    display_settings=display_settings,
                    page_instance_id=page_instance_id,
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid display settings",
                    key=existing_key,
                    error=str(e),
                )
                continue
            new_cache_key = nb_html_key.cache_key
            if dry_run:
                self._logger.info(
                    "Would rename key",
                    old_key=existing_key,
                    new_key=new_cache_key,
                )
            else:
                await self._html_store.rename_key(existing_key, new_cache_key)
                self._logger.info(
                    "Renamed html cache key",
                    old_key=existing_key,
                    new_key=new_cache_key,
                )
            key_count += 1

        return key_count
