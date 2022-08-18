"""The Page storage layer."""

from __future__ import annotations

from typing import List, Optional

from safir.database import datetime_from_db, datetime_to_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_scoped_session

from timessquare.dbschema.page import SqlPage
from timessquare.domain.githubtree import (
    GitHubNode,
    GitHubNodeType,
    GitHubTreeQueryResult,
)
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
            github_commit=page.github_commit,
            repository_path_prefix=page.repository_path_prefix,
            repository_display_path_prefix=page.repository_display_path_prefix,
            repository_path_stem=page.repository_path_stem,
            repository_source_extension=page.repository_source_extension,
            repository_sidecar_extension=page.repository_sidecar_extension,
            repository_source_sha=page.repository_source_sha,
            repository_sidecar_sha=page.repository_sidecar_sha,
        )
        self._session.add(new_page)

    async def update_page(self, page: PageModel) -> None:
        """Update an existing page."""
        statement = select(SqlPage).where(SqlPage.name == page.name).limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            # FIXME raise an database integrity error instead?
            return None

        parameters_json = {
            name: parameter.schema
            for name, parameter in page.parameters.items()
        }
        authors_json = [a.to_dict() for a in page.authors]
        date_deleted = (
            datetime_to_db(page.date_deleted) if page.date_deleted else None
        )

        # These are all fields that are considered "updatable", which is a
        # subset of all columns in SqlPage
        sql_page.ipynb = page.ipynb
        sql_page.parameters = parameters_json
        sql_page.title = page.title
        sql_page.authors = authors_json
        sql_page.tags = page.tags
        sql_page.date_deleted = date_deleted
        sql_page.description = page.description
        sql_page.cache_ttl = page.cache_ttl
        sql_page.repository_path_stem = page.repository_path_stem
        sql_page.repository_source_extension = page.repository_source_extension
        sql_page.repository_sidecar_extension = (
            page.repository_sidecar_extension
        )
        sql_page.repository_source_sha = page.repository_source_sha
        sql_page.repository_sidecar_sha = page.repository_sidecar_sha

    async def get(self, name: str) -> Optional[PageModel]:
        """Get a page based on the API slug (name), or get `None` if the
        page does not exist.
        """
        statement = select(SqlPage).where(SqlPage.name == name).limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            return None

        return self._rehydrate_page_from_sql(sql_page)

    async def get_github_backed_page(
        self, display_path: str, commit: Optional[str] = None
    ) -> Optional[PageModel]:
        """Get a GitHub-backed page based on the display path, or get `None`
        if the page does not exist.

        Parameters
        ----------
        display_path : str
            The GitHub display path, formatted ``owner/repo/file_path``.
        commit : str, optional
            The Git commit, if this page is associated with a GitHub Check Run.
        """
        path_parts = display_path.split("/")
        github_owner = path_parts[0]
        github_repo = path_parts[1]
        path_stem = path_parts[-1]
        if len(path_parts) > 3:
            path_prefix = "/".join(path_parts[2:-1])
        else:
            path_prefix = ""

        statement = (
            select(SqlPage)
            .where(SqlPage.github_owner == github_owner)
            .where(SqlPage.github_repo == github_repo)
            .where(SqlPage.repository_path_stem == path_stem)
            .where(SqlPage.repository_display_path_prefix == path_prefix)
            .where(SqlPage.date_deleted == None)  # noqa: E711
        )
        if commit:
            statement = statement.where(SqlPage.github_commit == commit)
        else:
            statement = statement.where(
                SqlPage.github_commit == None  # noqa: E711
            )
        statement = statement.limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            return None

        return self._rehydrate_page_from_sql(sql_page)

    async def list_pages_for_repository(
        self, *, owner: str, name: str, commit: Optional[str] = None
    ) -> List[PageModel]:
        """Get all pages backed by a specific GitHub repository.

        Parameters
        ----------
        owner : str
            The login name of the repository owner.
        name : str
            The repository name.
        commit : str, optional
            The commit, if listing pages for a specific GitHub Check Run.
        """
        statement = (
            select(SqlPage)
            .where(SqlPage.github_owner == owner)
            .where(SqlPage.github_repo == name)
            .where(SqlPage.date_deleted == None)  # noqa: E711
        )
        if commit:
            statement = statement.where(SqlPage.github_commit == commit)
        else:
            statement = statement.where(
                SqlPage.github_commit == None  # noqa: E711
            )
        result = await self._session.execute(statement)
        return [
            self._rehydrate_page_from_sql(sql_page)
            for sql_page in result.scalars()
        ]

    def _rehydrate_page_from_sql(self, sql_page: SqlPage) -> PageModel:
        """Create a page domain model from the SQL result."""
        parameters = {
            name: PageParameterSchema.create(schema)
            for name, schema in sql_page.parameters.items()
        }

        date_deleted = (
            datetime_from_db(sql_page.date_added)
            if sql_page.date_deleted
            else None
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
            github_commit=sql_page.github_commit,
            repository_path_prefix=sql_page.repository_path_prefix,
            repository_display_path_prefix=(
                sql_page.repository_display_path_prefix
            ),
            repository_path_stem=sql_page.repository_path_stem,
            repository_source_extension=sql_page.repository_source_extension,
            repository_sidecar_extension=sql_page.repository_sidecar_extension,
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
        statement = (
            select(SqlPage.name, SqlPage.title)
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .order_by(SqlPage.name)
        )
        result = await self._session.execute(statement)
        return [
            PageSummaryModel(name=name, title=title)
            for name, title in result.all()
        ]

    async def get_github_tree(self) -> List[GitHubNode]:
        """Get the tree of GitHub-backed pages, organized hierarchically by
        owner/repository/directory/page.
        """
        owners_statement = (
            select(SqlPage.github_owner)
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .where(SqlPage.github_commit == None)  # noqa: E711
            .distinct(SqlPage.github_owner)
        )
        result = await self._session.execute(owners_statement)

        nodes: List[GitHubNode] = []
        for owner_name in result.scalars():
            node = await self._generate_node_for_owner(owner_name)
            nodes.append(node)

        return nodes

    async def _generate_node_for_owner(self, owner_name: str) -> GitHubNode:
        statement = (
            select(  # order matches GitHubTreeQueryResult
                SqlPage.github_owner,
                SqlPage.github_repo,
                SqlPage.github_commit,
                SqlPage.repository_display_path_prefix,
                SqlPage.title,
                SqlPage.repository_path_stem,
            )
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .where(SqlPage.github_commit == None)  # noqa: E711
            .where(SqlPage.github_owner == owner_name)
            .order_by(
                SqlPage.github_owner.asc(),
                SqlPage.github_repo.asc(),
                SqlPage.repository_display_path_prefix,
                SqlPage.title,
            )
        )
        result = await self._session.execute(statement)

        tree_inputs = [
            GitHubTreeQueryResult(
                github_owner=row[0],
                github_repo=row[1],
                github_commit=row[2],
                path_prefix=row[3],
                title=row[4],
                path_stem=row[5],
            )
            for row in result.all()
        ]

        owner_node = GitHubNode(
            node_type=GitHubNodeType.owner,
            title=owner_name,
            path_segments=[owner_name],
            github_commit=None,
            contents=[],
        )
        for tree_input in tree_inputs:
            owner_node.insert_node(tree_input)

        return owner_node

    async def get_github_pr_tree(
        self, *, owner: str, repo: str, commit: str
    ) -> List[GitHubNode]:
        """Get the tree of GitHub-backed pages for a pull request commit."""
        statement = (
            select(  # order matches GitHubTreeQueryResult
                SqlPage.github_owner,
                SqlPage.github_repo,
                SqlPage.github_commit,
                SqlPage.repository_display_path_prefix,
                SqlPage.title,
                SqlPage.repository_path_stem,
            )
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .where(SqlPage.github_commit == commit)
            .where(SqlPage.github_owner == owner)
            .order_by(
                SqlPage.repository_display_path_prefix,
                SqlPage.title,
            )
        )
        result = await self._session.execute(statement)

        tree_inputs = [
            GitHubTreeQueryResult(
                github_owner=row[0],
                github_repo=row[1],
                github_commit=row[2],
                path_prefix=row[3],
                title=row[4],
                path_stem=row[5],
            )
            for row in result.all()
        ]
        if len(tree_inputs) == 0:
            return []

        # Create a root node for the repo to use its insert_input method
        # for sorting the tree and creating directories as needed
        repo_node = GitHubNode(
            node_type=GitHubNodeType.repo,
            path_segments=[owner, repo],
            github_commit=commit,
            title=repo,
            contents=[],
        )
        for tree_input in tree_inputs:
            repo_node.insert_node(tree_input)

        return repo_node.contents
