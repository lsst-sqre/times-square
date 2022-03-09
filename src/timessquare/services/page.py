"""The parmeterized notebook page service."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.noteburstjob import (
    NoteburstJobModel,
    NoteburstJobResponseModel,
    NoteburstJobStatus,
)
from timessquare.domain.page import PageModel, PageSummaryModel
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

    def create_page_with_notebook(self, name: str, ipynb: str) -> None:
        """Create a page resource given the parameterized Jupyter Notebook
        content.
        """
        page = PageModel.create(name=name, ipynb=ipynb)
        self._page_store.add(page)

    async def get_page(self, name: str) -> PageModel:
        """Get the page from the data store, given its name."""
        page = await self._page_store.get(name)
        if page is None:
            raise PageNotFoundError(name)
        return page

    async def get_page_summaries(self) -> List[PageSummaryModel]:
        """Get page summaries."""
        return await self._page_store.list_page_summaries()

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

        # First try to get HTML from redis cache
        nbhtml = await self._html_store.get(
            page_name=page.name, parameters=resolved_parameters
        )
        if nbhtml is not None:
            self._logger.debug("Got HTML from cache")
            return nbhtml

        # Second, look if there's an existing job request. If the job is
        # done this renders it into HTML; otherwise it triggers a noteburst
        # request, but does not return any HTML for this request.
        nbhtml = await self._get_html_from_noteburst_job(
            page=page, resolved_parameters=resolved_parameters
        )
        if nbhtml is not None:
            return nbhtml

        return None

    async def _get_html_from_noteburst_job(
        self, *, page: PageModel, resolved_parameters: Mapping[str, Any]
    ) -> Optional[NbHtmlModel]:
        """Convert a noteburst job for a given page and parameters into
        HTML (caching that HTML as well), and triggering a new noteburst
        """
        # Is there an existing job in the noteburst job store?
        job = await self._job_store.get(
            page_name=page.name, parameters=resolved_parameters
        )
        if not job:
            self._logger.debug("No existing noteburst job available")
            # A record of a noteburst job is not available. Send a request
            # to noteburst.
            await self._request_noteburst_execution(
                page=page, resolved_parameters=resolved_parameters
            )
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
                html = page.render_html(ipynb)
                nbhtml = NbHtmlModel.create_from_noteburst_result(
                    page_name=page.name,
                    html=html,
                    parameters=resolved_parameters,
                    noteburst_result=noteburst_response,
                )
                # FIXME make lifetime a setting of page for pages that aren't
                # idempotent.
                await self._html_store.store(nbhtml=nbhtml, lifetime=None)
                self._logger.debug("Stored new HTML")
                await self._job_store.delete(
                    page_name=page.name, parameters=resolved_parameters
                )
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
            await self._job_store.delete(
                page_name=page.name, parameters=resolved_parameters
            )
            await self._request_noteburst_execution(
                page=page, resolved_parameters=resolved_parameters
            )
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
        self, *, page: PageModel, resolved_parameters: Mapping[str, Any]
    ) -> None:
        """Request a notebook execution for a given page and parameters,
        and store the job.
        """
        ipynb = page.render_parameters(resolved_parameters)
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

            r2 = await self._http_client.get(
                f"{config.environment_url}/noteburst/",
                headers=self._noteburst_auth_header,
            )
            self._logger.warning(
                "Pinged noteburst metadata",
                noteburst_status=r2.status_code,
                noteburst_body=r2.text,
                noteburst_req_url=r2.request.url,
                noteburst_req_headers=r2.request.headers,
            )

            return None

        response_data = r.json()
        job = NoteburstJobModel.from_noteburst_response(response_data)
        await self._job_store.store(
            job=job, page_name=page.name, parameters=resolved_parameters
        )
        self._logger.info(
            "Requested noteburst notebook execution",
            page_name=page.name,
            parameters=resolved_parameters,
            job_url=job.job_url,
        )

    @property
    def _noteburst_auth_header(self) -> Dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {config.gafaelfawr_token.get_secret_value()}"
            )
        }
