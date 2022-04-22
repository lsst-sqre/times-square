"""The Page storage layer."""

from __future__ import annotations

from typing import List, Optional

from safir.database import datetime_from_db, datetime_to_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_scoped_session

from timessquare.dbschema.page import SqlPage
from timessquare.domain.page import (
    PageModel,
    PageParameterSchema,
    PageSummaryModel,
    PersonModel,
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
            name=page.name,
            ipynb=page.ipynb,
            parameters=parameters_json,
            title=page.title,
            date_added=datetime_to_db(page.date_added),
            authors=[p.to_dict() for p in page.authors],
            tags=page.tags,
            uploader_username=page.uploader_username,
            date_deleted=(
                datetime_to_db(page.date_deleted)
                if page.date_deleted
                else None
            ),
            description=page.description,
            cache_ttl=page.cache_ttl,
            github_owner=page.github_owner,
            github_repo=page.github_repo,
            repository_path_prefix=page.repository_path_prefix,
            repository_display_path_prefix=page.repository_display_path_prefix,
            repository_source_filename=page.repository_source_filename,
            repository_sidecar_filename=page.repository_sidecar_filename,
            repository_source_sha=page.repository_source_sha,
            repository_sidecar_sha=page.repository_sidecar_sha,
        )
        self._session.add(new_page)

    async def get(self, name: str) -> Optional[PageModel]:
        """Get a page based on the API slug (name), or get `None` if the
        page does not exist.
        """
        statement = select(SqlPage).where(SqlPage.name == name).limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            return None

        return self._rehydrate_page_from_sql(sql_page)

    def _rehydrate_page_from_sql(self, sql_page) -> PageModel:
        """Create a page domain model from the SQL result."""
        parameters = {
            name: PageParameterSchema.create(schema)
            for name, schema in sql_page.parameters.items()
        }

        date_deleted = (
            datetime_from_db(sql_page.date_added) if sql_page.date else None
        )

        authors = [PersonModel.from_dict(p) for p in sql_page.authors]

        return PageModel(
            name=sql_page.name,
            ipynb=sql_page.ipynb,
            parameters=parameters,
            title=sql_page.title,
            date_added=datetime_from_db(sql_page.date_added),
            date_deleted=date_deleted,
            authors=authors,
            tags=sql_page.tags,
            uploader_username=sql_page.uploader_username,
            description=sql_page.description,
            cache_ttl=sql_page.cache_ttl,
            github_owner=sql_page.github_owner,
            github_repo=sql_page.github_repo,
            repository_path_prefix=sql_page.repository_path_prefix,
            repository_display_path_prefix=(
                sql_page.repository_display_path_prefix
            ),
            repository_source_filename=sql_page.repository_source_filename,
            repository_sidecar_filename=sql_page.repository_sidecar_filename,
            repository_source_sha=sql_page.repository_source_sha,
            repository_sidecar_sha=sql_page.repository_sidecar_sha,
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
