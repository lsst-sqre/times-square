"""The Page storage layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from timessquare.dbschema.page import SqlPage
from timessquare.domain.page import PageModel, PageParameterSchema

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PageStore:
    """Manage page resources in the SQL database.

    Parameters
    ----------
    session : `sqlalchemy.ext.asyncio.AsyncSession`
        The database session proxy.
    """

    def __init__(self, session: AsyncSession) -> None:
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
