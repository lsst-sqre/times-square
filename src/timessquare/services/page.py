"""The parmeterized notebook page service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.domain.githubtree import GitHubNode
from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.noteburstjob import (
    NoteburstJobModel,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)
from timessquare.domain.page import (
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

    async def create_page_with_notebook_from_upload(
        self,
        ipynb: str,
        title: str,
        uploader_username: str,
        description: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
        authors: Optional[List[PersonModel]] = None,
    ) -> str:
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
        return await self.add_page(page)

    async def add_page(self, page: PageModel, *, execute: bool = True) -> str:
        """Add a page to the page store.

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
        self._page_store.add(page)
        if execute:
            await self._request_notebook_execution_for_page_defaults(page)
        return page.name

    async def get_page(self, name: str) -> PageModel:
        """Get the page from the data store, given its name."""
        page = await self._page_store.get(name)
        if page is None:
            raise PageNotFoundError(name)
        return page

    async def get_page_summaries(self) -> List[PageSummaryModel]:
        """Get page summaries."""
        return await self._page_store.list_page_summaries()

    async def get_pages_for_repo(
        self, owner: str, name: str
    ) -> List[PageModel]:
        """Get all pages backed by a specific GitHub repository."""
        return await self._page_store.list_pages_for_repository(
            owner=owner, name=name
        )

    async def get_github_tree(self) -> List[GitHubNode]:
        """Get the tree of GitHub-backed pages."""
        return await self._page_store.get_github_tree()

    async def update_page(self, page: PageModel) -> None:
        """Update the page in the database."""
        await self._page_store.update_page(page)
        await self._request_notebook_execution_for_page_defaults(page)

    async def _request_notebook_execution_for_page_defaults(
        self, page: PageModel
    ) -> None:
        """Request noteburst execution of with page's default values.

        This is useful for the `add_page` and `update_page` methods to start
        notebook execution as soon as possible.
        """
        resolved_parameters = page.resolve_and_validate_parameters({})
        page_instance = PageInstanceModel(
            name=page.name, values=resolved_parameters, page=page
        )
        await self._request_noteburst_execution(page_instance)

    async def soft_delete_page(self, page: PageModel) -> None:
        """Soft delete a page by setting its date_deleted field."""
        page.date_deleted = datetime.now(timezone.utc)
        await self._page_store.update_page(page)

    async def soft_delete_pages_for_repo(self, owner: str, name: str) -> None:
        """Soft delete all pages backed by a specific GitHub repository."""
        for page in await self.get_pages_for_repo(owner=owner, name=name):
            await self.soft_delete_page(page)

    async def render_page_template(
        self, name: str, parameters: Mapping[str, Any]
    ) -> str:
        """Render a page's jupyter notebook, with the given parameter values.

        Parameters
        ----------
        name : `str`
            Name (URL slug) of the page.
        parameters : `dict`
            Parameter values, keyed by parameter names. If parameters are
            missing, the default value is used instead.
        """
        page = await self.get_page(name)
        resolved_parameters = page.resolve_and_validate_parameters(parameters)
        rendered_notebook = page.render_parameters(resolved_parameters)
        return rendered_notebook

    async def get_html(
        self, *, name: str, parameters: Mapping[str, Any]
    ) -> Optional[NbHtmlModel]:
        """Get the HTML for a page given a set of parameter values, first
        from a cache or triggering a rendering if not available.

        Returns
        -------
        nbhtml : `NbHtmlModel` or `None`
            The NbHtmlModel if available, or `None` if the executed notebook is
            not presently available.
        """
        page = await self.get_page(name)
        resolved_parameters = page.resolve_and_validate_parameters(parameters)

        page_instance = PageInstanceModel(
            name=page.name, values=resolved_parameters, page=page
        )

        # First try to get HTML from redis cache
        nbhtml = await self._html_store.get(page_instance)
        if nbhtml is not None:
            self._logger.debug("Got HTML from cache")
            return nbhtml

        # Second, look if there's an existing job request. If the job is
        # done this renders it into HTML; otherwise it triggers a noteburst
        # request, but does not return any HTML for this request.
        return await self._get_html_from_noteburst_job(page_instance)

    async def _get_html_from_noteburst_job(
        self, page_instance: PageInstanceModel
    ) -> Optional[NbHtmlModel]:
        """Convert a noteburst job for a given page and parameters into
        HTML (caching that HTML as well), and triggering a new noteburst

        Parameters
        ----------
        page_instance : `PageInstanceModel`
            The page instance (consisting of resolved parameters).

        Returns
        -------
        nbhtml : `NbHtmlModel` or `None`
            The NbHtmlModel if available, or `None` if the executed notebook is
            not presently available.
        """
        # Is there an existing job in the noteburst job store?
        job = await self._job_store.get(page_instance)
        if not job:
            self._logger.debug("No existing noteburst job available")
            # A record of a noteburst job is not available. Send a request
            # to noteburst.
            await self._request_noteburst_execution(page_instance)
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
                assert ipynb
                html = page_instance.page.render_html(ipynb)
                nbhtml = NbHtmlModel.create_from_noteburst_result(
                    page_id=page_instance,
                    html=html,
                    noteburst_result=noteburst_response,
                )
                # FIXME make lifetime a setting of page for pages that aren't
                # idempotent.
                await self._html_store.store_nbhtml(
                    nbhtml=nbhtml, lifetime=None
                )
                self._logger.debug("Stored new HTML")
                await self._job_store.delete(page_instance)
                self._logger.debug("Deleted old job record")
                return nbhtml

            else:
                # Noteburst job isn't complete
                return None

        elif r.status_code != 404:
            # Noteburst lost the job; delete our record and try again
            self._logger.warning(
                "Got a 404 from a noteburst job", job_url=job.job_url
            )
            await self._job_store.delete(page_instance)
            await self._request_noteburst_execution(page_instance)
        else:
            # server error from noteburst
            self._logger.warning(
                "Got unknown response from noteburst job",
                job_url=job.job_url,
                noteburst_status=r.status_code,
                noteburst_body=r.text,
            )
        return None

    async def _request_noteburst_execution(
        self, page_instance: PageInstanceModel
    ) -> None:
        """Request a notebook execution for a given page and parameters,
        and store the job.
        """
        ipynb = page_instance.page.render_parameters(page_instance.values)
        r = await self._http_client.post(
            f"{config.environment_url}/noteburst/v1/notebooks/",
            json={
                "ipynb": ipynb,
                "kernel_name": "LSST",  # TODO make a setting per page?
            },
            headers=self._noteburst_auth_header,
        )
        if r.status_code != 202:
            self._logger.warning(
                "Error requesting noteburst execution",
                noteburst_status=r.status_code,
                noteburst_body=r.text,
            )

            return None

        response_data = r.json()
        job = NoteburstJobModel.from_noteburst_response(response_data)
        await self._job_store.store_job(job=job, page_id=page_instance)
        self._logger.info(
            "Requested noteburst notebook execution",
            page_name=page_instance.name,
            parameters=page_instance.values,
            job_url=job.job_url,
        )

    @property
    def _noteburst_auth_header(self) -> Dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {config.gafaelfawr_token.get_secret_value()}"
            )
        }
