"""The Page storage layer."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_scoped_session

from timessquare.dbschema.page import SqlPage
from timessquare.domain.page import (
    PageModel,
    PageParameterSchema,
    PageSummaryModel,
)


class PageStore:
    """Manage page resources in the SQL database.

    Parameters
    ----------
    session : `sqlalchemy.ext.asyncio.async_scoped_session`
        The database session proxy.
    """

    def __init__(self, session: async_scoped_session) -> None:
        self._session = session

    def add(self, page: PageModel) -> None:
        """Add a new page."""
        parameters_json = {
            name: parameter.schema
            for name, parameter in page.parameters.items()
        }
        new_page = SqlPage(
            name=page.name, ipynb=page.ipynb, parameters=parameters_json
        )
        self._session.add(new_page)

    async def get(self, name: str) -> Optional[PageModel]:
        """Get a page, or `None` if the page does not exist."""
        statement = select(SqlPage).where(SqlPage.name == name).limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            return None

        parameters = {
            name: PageParameterSchema.create(schema)
            for name, schema in sql_page.parameters.items()
        }

        return PageModel(
            name=sql_page.name,
            ipynb=sql_page.ipynb,
            parameters=parameters,
        )

    async def list_page_summaries(self) -> List[PageSummaryModel]:
        """Get a listing of page summaries (excludes the ipynb and
        parameters).

        Rather than a list of `PageModel` objects, Times Square's page
        listing APIs generally need to just provide a listing of page titles
        and metadata that's usefulf or populating index UIs. That's why
        """
        # TODO consider adding other fields like title, description,
        # date-updated, etc.. Anything that index UIs might find useful.
        statement = select(SqlPage.name).order_by(SqlPage.name)
        result = await self._session.scalars(statement)
        return [PageSummaryModel(name=name) for name in result.all()]
