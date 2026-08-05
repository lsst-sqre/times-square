"""The parmeterized notebook page service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from safir.arq import ArqQueue
from structlog.stdlib import BoundLogger

from ..domain.executionoutcome import (
    ExecutionOutcomeKind,
    NotebookExecutionFailure,
    classify_noteburst_outcome,
)
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
from ..storage.nbexecutionfailurestore import NbExecutionFailureStore
from ..storage.nbhtmlcache import NbHtmlCacheStore
from ..storage.noteburst import (
    NoteburstApi,
    NoteburstJobModel,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)
from ..storage.noteburstjobstore import NoteburstJobStore
from ..storage.page import PageStore

EVENTS_POLL_BASE_INTERVAL = 1.0
"""Seconds between polls of a page instance's execution and rendering state by
the HTML events stream (`PageService.get_html_events_iter`) while that state is
moving: a Noteburst job record exists, or the last poll changed the payload.
"""

EVENTS_POLL_MAX_INTERVAL = 10.0
"""Maximum seconds between polls of a page instance's execution and rendering
state by the HTML events stream (`PageService.get_html_events_iter`).

An idle subscription — no Noteburst job record, and an unchanged payload —
backs off towards this interval so that a long-lived stream on a settled page
instance costs a fraction of the Redis lookups a fixed base interval would.
"""


@dataclass(frozen=True, slots=True)
class EventsPollResult:
    """The result of one poll of a page instance's execution and rendering
    state by the HTML events stream.
    """

    payload: HtmlEventsModel
    """The payload describing the state the poll found."""

    job_exists: bool
    """Whether a Noteburst job record existed for the page instance.

    A job record means an execution is in flight, so the state is expected to
    move and the stream keeps polling at its base interval.
    """


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
        *,
        page_store: PageStore,
        html_cache: NbHtmlCacheStore,
        job_store: NoteburstJobStore,
        execution_failure_store: NbExecutionFailureStore,
        http_client: AsyncClient,
        logger: BoundLogger,
        arq_queue: ArqQueue,
    ) -> None:
        self._page_store = page_store
        self._html_store = html_cache
        self._job_store = job_store
        self._execution_failure_store = execution_failure_store
        self._http_client = http_client
        self._logger = logger
        self._arq_queue = arq_queue
        self.noteburst_api = NoteburstApi(http_client=http_client)

    async def create_page_with_notebook_from_upload(
        self,
        *,
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
        self._logger.debug(
            "Adding page to store",
            page_name=page.name,
            title=page.title,
            ipynb=page.ipynb,
        )
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

    async def update_page_in_store(
        self, page: PageModel, *, drop_html_cache: bool = True
    ) -> None:
        """Update the page in the database.

        Parameters
        ----------
        page
            The page model to update.
        drop_html_cache
            If `True`, delete the HTML cache for this page. This is useful
            when the page is updated and the HTML cache needs to be
            invalidated. Set to `False` when updating the page in a way
            that does not affect the cached HTML results.

        Notes
        -----
        Algorithm is:

        1. Update the page in Postgres
        2. Delete all cached HTML for the page from redis
        """
        await self._page_store.update_page(page)
        if drop_html_cache is True:
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
        execution_error: NotebookExecutionFailure | None = None
        if nbhtml is None:
            job = await self._job_store.get_instance(page_instance.id)
            if job is not None:
                # A live job record always wins over a cached failure: a
                # failure marker written by a concurrent poll of a superseded
                # job must not hide the execution that is still in flight.
                (
                    nbhtml,
                    execution_error,
                ) = await self._get_html_from_noteburst_job(
                    page_instance=page_instance,
                    display_settings=html_key.display_settings,
                    job=job,
                )
            else:
                # With no job in flight, a cached terminal failure
                # short-circuits re-execution so that a persistently broken
                # notebook does not trigger a fresh Noteburst execution on
                # every poll.
                execution_error = (
                    await self._execution_failure_store.get_instance(
                        page_instance.id
                    )
                )
                if execution_error is None:
                    self._logger.debug("No existing noteburst job available")
                    await self.request_noteburst_execution(page_instance)

        return NbHtmlStatusModel(
            nb_html=nbhtml,
            nb_html_key=html_key,
            page_instance=page_instance,
            execution_error=execution_error,
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
        job: NoteburstJobModel,
    ) -> tuple[NbHtmlModel | None, NotebookExecutionFailure | None]:
        """Convert a noteburst job for a given page and parameter values into
        HTML (caching that HTML as well), and triggering a new noteburst job if
        noteburst lost the job.

        Parameters
        ----------
        page_instance : `PageInstanceModel`
            The page instance (consisting of resolved parameter values).
        display_settings : `NbDisplaySettings`
            A display parameter passed to `NbHtml.create_from_noteburst_result`
            that indicates whether the returned HTML should include code input
            cells.
        job : `NoteburstJobModel`
            The job record from the noteburst job store.

        Returns
        -------
        tuple
            A 2-tuple of the `NbHtmlModel` (or `None` if the executed notebook
            is not presently available) and a `NotebookExecutionFailure` (or
            `None` if the notebook did not terminally fail to execute).
        """
        r = await self.noteburst_api.get_job(str(job.job_url))

        if r.status_code == 404:
            # Noteburst lost the job; delete our record and try again
            self._logger.warning(
                "Got a 404 from a noteburst job", job_url=job.job_url
            )
            await self._job_store.delete_instance(page_instance.id)
            await self.request_noteburst_execution(page_instance)
            return None, None

        elif r.status_code >= 500:
            # server error from noteburst
            self._logger.warning(
                "Got unknown response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
            )
            return None, None
        elif r.data is None:
            self._logger.warning(
                "Got empty response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
            )
            return None, None

        if r.data.status == NoteburstJobStatus.complete:
            failure = await self._handle_completed_outcome(
                page_instance=page_instance, noteburst_response=r.data
            )
            if failure is not None:
                return None, failure

            html_renders = (
                await self.render_nbhtml_matrix_from_noteburst_response(
                    page_instance=page_instance,
                    noteburst_response=r.data,
                )
            )
            # return the specific HTML render that the client asked for
            return html_renders[display_settings], None

        else:
            # Noteburst job isn't complete
            return None, None

    async def _handle_completed_outcome(
        self,
        *,
        page_instance: PageInstanceModel,
        noteburst_response: NoteburstJobResponseModel,
    ) -> NotebookExecutionFailure | None:
        """Classify a completed Noteburst response and handle the two
        non-renderable outcomes.

        Parameters
        ----------
        page_instance
            The page instance the execution belongs to.
        noteburst_response
            A Noteburst job response with a ``complete`` status.

        Returns
        -------
        NotebookExecutionFailure or None
            The terminal failure when the execution failed at the
            infrastructure level, or `None` when the response carries an
            executed notebook and the caller should render it.

        Raises
        ------
        RuntimeError
            Raised if Noteburst reported a successful execution but returned
            no executed notebook.

        Notes
        -----
        An execution failure is returned rather than raised because it is an
        expected terminal outcome, not a bug: raising would surface it as a
        generic worker exception in Slack. A contract violation is a genuine
        bug, so it raises loudly instead of being silently swallowed.
        """
        outcome = classify_noteburst_outcome(noteburst_response)
        if outcome.kind is ExecutionOutcomeKind.execution_failure:
            return await self._handle_execution_failure(
                page_instance=page_instance,
                noteburst_response=noteburst_response,
                failure=outcome.failure,
            )
        if outcome.kind is ExecutionOutcomeKind.contract_violation:
            raise RuntimeError(outcome.contract_violation_message)
        return None

    async def _handle_execution_failure(
        self,
        *,
        page_instance: PageInstanceModel,
        noteburst_response: NoteburstJobResponseModel,
        failure: NotebookExecutionFailure | None,
    ) -> NotebookExecutionFailure | None:
        """Handle a terminal notebook execution failure.

        Logs a structured warning, caches the failure marker to prevent a
        re-execution storm, and deletes the stale Noteburst job-store record.
        """
        if failure is None:
            # Defensive: an execution_failure outcome always carries a failure.
            return None
        self._logger.warning(
            "Notebook execution failed",
            page_name=page_instance.page_name,
            parameters=page_instance.values,
            execution_error_code=failure.code,
            execution_error_message=failure.message,
            job_url=str(noteburst_response.self_url),
        )
        await self._execution_failure_store.store_failure(
            failure=failure, page_id=page_instance.id
        )
        deleted_job = await self._job_store.delete_instance(page_instance.id)
        if deleted_job:
            self._logger.debug("Deleted stale job record after failure")
        return failure

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
        # A new execution supersedes any cached terminal failure. Clearing it
        # here covers every path that deliberately requests a re-run (a page
        # update, a soft delete of the HTML, or a background recompute) so a
        # stale failure cannot mask a fixed notebook for the remainder of the
        # failure's lifetime.
        await self._execution_failure_store.delete_instance(page_instance.id)

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
            outcome = classify_noteburst_outcome(noteburst_response)
            if outcome.failure is not None:
                raise RuntimeError(
                    f"Notebook execution failed: {outcome.failure.message}"
                )
            raise RuntimeError(
                outcome.contract_violation_message
                or "Noteburst returned no executed notebook."
            )
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

    async def _resolve_events_execution_error(
        self,
        *,
        page_instance: PageInstanceModel,
        job: NoteburstJobModel | None,
        noteburst_data: NoteburstJobResponseModel | None,
        nbhtml: NbHtmlModel | None,
    ) -> NotebookExecutionFailure | None:
        """Resolve a terminal execution failure for one SSE events iteration.

        Mirrors the gating of the interactive path: the failure machinery is
        only consulted when no HTML is cached for the page instance. While
        cached HTML is available — as during a background refresh of a
        soft-deleted render — the stream reports that HTML and never goes
        terminal, leaving failure handling of the refresh to the background
        worker that owns it.

        With no HTML cached, classifies a completed Noteburst job; on execution
        failure performs the same cleanup as the interactive path (log a
        structured warning, cache the failure marker, and delete the stale job
        record). When there is additionally no job in flight, falls back to a
        previously cached failure marker so the stream keeps reporting the
        terminal failure after the stale job record is deleted.

        As on the interactive path, a live job record always wins over a cached
        failure marker: a marker written by a concurrent poll of a superseded
        job must not hide an execution that is still in flight.
        """
        if nbhtml is not None:
            return None

        execution_error: NotebookExecutionFailure | None = None
        if (
            noteburst_data is not None
            and noteburst_data.status == NoteburstJobStatus.complete
        ):
            execution_error = await self._handle_completed_outcome(
                page_instance=page_instance,
                noteburst_response=noteburst_data,
            )

        if execution_error is None and job is None:
            execution_error = await self._execution_failure_store.get_instance(
                page_instance.id
            )
        return execution_error

    async def _build_events_payload(
        self,
        *,
        page_instance: PageInstanceModel,
        html_key: NbHtmlKey,
        query_params: Mapping[str, Any],
        html_base_url: str,
    ) -> EventsPollResult:
        """Build one SSE events payload from the current execution and
        rendering state of a page instance.

        Gathers the state the events stream reports: the Noteburst job record
        for the page instance (and, if one exists, its current state from
        Noteburst), the cached HTML for the requested display settings, and any
        terminal execution failure resolved by
        `_resolve_events_execution_error`.

        Parameters
        ----------
        page_instance
            The page instance the events stream is reporting on.
        html_key
            The cache key for the HTML rendering, which combines the page
            instance with the requested display settings.
        query_params
            The query parameters of the events request, used to build the HTML
            URL when no HTML is cached yet.
        html_base_url
            The base URL of the page instance's HTML endpoint.

        Returns
        -------
        EventsPollResult
            The payload describing the current state of the page instance,
            along with whether a Noteburst job record backed it.
        """
        job = await self._job_store.get_instance(page_instance.id)
        noteburst_data: NoteburstJobResponseModel | None = None
        if job:
            self._logger.debug(
                "Got job in events loop", job_url=str(job.job_url)
            )
            noteburst_response = await self.noteburst_api.get_job(
                str(job.job_url)
            )
            if noteburst_response.data:
                noteburst_data = noteburst_response.data

        nbhtml = await self._html_store.get_instance(html_key)

        execution_error = await self._resolve_events_execution_error(
            page_instance=page_instance,
            job=job,
            noteburst_data=noteburst_data,
            nbhtml=nbhtml,
        )

        return EventsPollResult(
            payload=HtmlEventsModel.create(
                page_instance=page_instance,
                noteburst_job=noteburst_data,
                nbhtml=nbhtml,
                request_query_params=query_params,
                html_base_url=html_base_url,
                execution_error=execution_error,
            ),
            job_exists=job is not None,
        )

    @staticmethod
    def _is_new_events_payload(
        *,
        payload: HtmlEventsModel,
        last_payload: HtmlEventsModel | None,
    ) -> bool:
        """Determine whether an events payload is new relative to the last one
        emitted on the stream, and therefore worth sending.

        The first payload of a stream is always new, so every subscriber gets
        an initial snapshot of the page instance's state. After that a payload
        is new when its serialization differs from the last one emitted.

        A terminal execution failure is reported once. Once the failure is
        emitted, the job record it came from is deleted, so the next poll
        rebuilds the same failure from the cached marker with the execution's
        dates and status nulled out. That is a strictly less informative
        restatement of a state the client already has, so a payload repeating
        the last emitted ``execution_error`` is not a new one.

        Parameters
        ----------
        payload
            The payload built from the page instance's current state.
        last_payload
            The last payload emitted on this stream, or `None` if the stream
            has not emitted anything yet.

        Returns
        -------
        bool
            `True` if the payload should be emitted.
        """
        if last_payload is None:
            return True
        if (
            payload.execution_error is not None
            and payload.execution_error == last_payload.execution_error
        ):
            return False
        return payload.model_dump_json() != last_payload.model_dump_json()

    @staticmethod
    def _next_events_poll_interval(
        *,
        interval: float,
        is_idle: bool,
        base_interval: float,
        max_interval: float,
    ) -> float:
        """Compute the interval to wait before the events stream's next poll of
        a page instance's execution and rendering state.

        A poll is idle when nothing is driving the page instance's state: no
        Noteburst job record exists for it, and the poll did not change the
        payload. Each consecutive idle poll doubles the interval, up to
        ``max_interval``, so that a subscription to a settled page instance
        stops costing a Redis lookup per second. Any poll that is not idle
        resets the interval to ``base_interval``, so a client sees a state
        change within a second of it happening.

        Parameters
        ----------
        interval
            The interval waited before the poll that just completed.
        is_idle
            Whether the poll that just completed was idle.
        base_interval
            The interval to poll at while the state is moving.
        max_interval
            The longest interval an idle stream backs off to.

        Returns
        -------
        float
            The number of seconds to wait before the next poll.
        """
        if not is_idle:
            return base_interval
        return min(interval * 2.0, max_interval)

    async def get_html_events_iter(
        self,
        name: str,
        query_params: Mapping[str, Any],
        html_base_url: str,
        *,
        base_poll_interval: float = EVENTS_POLL_BASE_INTERVAL,
        max_poll_interval: float = EVENTS_POLL_MAX_INTERVAL,
    ) -> AsyncIterator[bytes]:
        """Get an iterator providing an event stream for the HTML rendering
        for a page instance.

        The stream emits one initial event as soon as the client subscribes,
        reporting whatever the current state is — including the all-null state
        of a page instance with no execution in flight and no cached HTML.
        After that it polls the page instance's state and emits an event only
        when the payload has changed, so a client that is up to date receives
        nothing until the state moves. The stream is never closed by the
        server: after a terminal execution failure it stays open and reports a
        later re-execution without the client resubscribing. Keep-alive is
        left to the SSE transport's comment pings.

        Polling adapts to the page instance. While an execution is in flight,
        or the state just changed, the stream polls at ``base_poll_interval``.
        Once it goes idle each consecutive unchanged poll doubles the interval,
        up to ``max_poll_interval``, so an idle subscription stops costing a
        set of Redis lookups every second; the first poll that finds a job
        record or a changed payload resets the interval.

        Parameters
        ----------
        name
            The name of the page.
        query_params
            The query parameters of the events request, which carry the page
            instance's parameter values and display settings.
        html_base_url
            The base URL of the page instance's HTML endpoint.
        base_poll_interval
            Seconds between polls while the page instance's state is moving.
            Overridable for testing; operationally this is
            `EVENTS_POLL_BASE_INTERVAL`.
        max_poll_interval
            The longest interval an idle stream backs off to. Overridable for
            testing; operationally this is `EVENTS_POLL_MAX_INTERVAL`.

        Returns
        -------
        collections.abc.AsyncIterator
            An iterator over the stream's encoded server-sent events.
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
            last_payload: HtmlEventsModel | None = None
            interval = base_poll_interval
            try:
                while True:
                    poll = await self._build_events_payload(
                        page_instance=page_instance,
                        html_key=html_key,
                        query_params=query_params,
                        html_base_url=html_base_url,
                    )
                    is_new = self._is_new_events_payload(
                        payload=poll.payload, last_payload=last_payload
                    )
                    if is_new:
                        self._logger.debug(
                            "Emitting payload in events loop",
                            payload=poll.payload,
                        )
                        last_payload = poll.payload
                        yield poll.payload.to_sse().encode()

                    previous_interval = interval
                    interval = self._next_events_poll_interval(
                        interval=interval,
                        is_idle=not (is_new or poll.job_exists),
                        base_interval=base_poll_interval,
                        max_interval=max_poll_interval,
                    )
                    if interval != previous_interval:
                        self._logger.debug(
                            "Changed events poll interval",
                            interval=interval,
                            previous_interval=previous_interval,
                        )
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                self._logger.debug("HTML events disconnected from client")
                # cleanup as necessary
                raise
            except Exception as e:
                self._logger.exception("Error in HTML events iterator", e=e)
                raise

        return iterator()
