"""The parmeterized notebook page service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from timessquare.domain.page import PageModel
from timessquare.exceptions import PageNotFoundError

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

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
        logger: BoundLogger,
    ) -> None:
        self._page_store = page_store
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
