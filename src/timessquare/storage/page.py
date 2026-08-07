"""The Page storage layer."""

from __future__ import annotations

from safir.database import datetime_from_db, datetime_to_db
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from timessquare.dbschema.page import SqlPage
from timessquare.domain.githubtree import (
    GitHubNode,
    GitHubNodeType,
    GitHubTreeQueryResult,
)
from timessquare.domain.page import PageModel, PageSummaryModel, PersonModel
from timessquare.domain.pageparameters import PageParameters


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
            name=page.name,
            ipynb=page.ipynb,
            parameters=parameters_json,
            title=page.title,
            date_added=datetime_to_db(page.date_added),
            authors=[p.to_dict() for p in page.authors],
            tags=page.tags,
            execution_timeout=page.timeout,
            schedule_rruleset=page.schedule_rruleset,
            schedule_enabled=page.schedule_enabled,
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
            github_repository_id=page.github_repository_id,
            github_owner_id=page.github_owner_id,
            github_installation_id=page.github_installation_id,
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
            return

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
        sql_page.execution_timeout = page.timeout
        sql_page.schedule_rruleset = page.schedule_rruleset
        sql_page.schedule_enabled = page.schedule_enabled
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
        # The GitHub identity columns are updatable so that a sync can heal
        # owner/repo strings that drifted through a rename or transfer, and
        # backfill the numeric IDs on pages that predate ID capture.
        sql_page.github_owner = page.github_owner
        sql_page.github_repo = page.github_repo
        sql_page.github_repository_id = page.github_repository_id
        sql_page.github_owner_id = page.github_owner_id
        sql_page.github_installation_id = page.github_installation_id

    async def get(self, name: str) -> PageModel | None:
        """Get a page based on the API slug (name), or get `None` if the
        page does not exist.
        """
        statement = select(SqlPage).where(SqlPage.name == name).limit(1)
        sql_page = await self._session.scalar(statement)
        if sql_page is None:
            return None

        return self._rehydrate_page_from_sql(sql_page)

    async def get_github_backed_page(
        self, display_path: str, commit: str | None = None
    ) -> PageModel | None:
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
        path_prefix = "/".join(path_parts[2:-1]) if len(path_parts) > 3 else ""

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
        self,
        *,
        owner: str,
        name: str,
        commit: str | None = None,
        repository_id: int | None = None,
    ) -> list[PageModel]:
        """Get all pages backed by a specific GitHub repository.

        Parameters
        ----------
        owner : str
            The login name of the repository owner.
        name : str
            The repository name.
        commit : str, optional
            The commit, if listing pages for a specific GitHub Check Run.
        repository_id : int, optional
            GitHub's stable numeric ID for the repository. When given, pages
            are matched on this ID — which survives renames and transfers —
            unioned with a name-based match restricted to pages that have no
            ID recorded yet.
        """
        name_match = and_(
            SqlPage.github_owner == owner, SqlPage.github_repo == name
        )
        if repository_id is None:
            repository_match = name_match
        else:
            repository_match = or_(
                SqlPage.github_repository_id == repository_id,
                and_(SqlPage.github_repository_id.is_(None), name_match),
            )
        statement = (
            select(SqlPage)
            .where(repository_match)
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

    async def list_pages_for_repository_id(
        self, *, repository_id: int
    ) -> list[PageModel]:
        """Get all live pages backed by a GitHub repository, matching on the
        repository's stable numeric ID alone.

        Unlike `list_pages_for_repository` this never matches on the stored
        ``owner``/``repo`` strings, so it is safe to use when those strings
        are known to be stale — after a transfer, for example, which frees
        the old name pair on GitHub immediately.

        Parameters
        ----------
        repository_id : int
            GitHub's stable numeric ID for the repository.

        Returns
        -------
        list of PageModel
            The repository's pages. Soft-deleted pages and pull-request
            preview pages are excluded.
        """
        statement = (
            select(SqlPage)
            .where(SqlPage.github_repository_id == repository_id)
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .where(SqlPage.github_commit == None)  # noqa: E711
        )
        result = await self._session.execute(statement)
        return [
            self._rehydrate_page_from_sql(sql_page)
            for sql_page in result.scalars()
        ]

    async def list_conflicting_repository_ids(
        self, *, owner: str, name: str, repository_id: int
    ) -> list[int]:
        """List the repository IDs of pages that hold an owner/repository
        name pair on behalf of some *other* GitHub repository.

        A non-empty result means the ``owner/name`` strings are stale: they
        still point at pages belonging to a repository that has since been
        renamed or transferred, and a repository that now answers to those
        names would collide with them on display paths.

        Parameters
        ----------
        owner : str
            The login name of the repository owner.
        name : str
            The repository name.
        repository_id : int
            GitHub's stable numeric ID for the repository claiming the names.

        Returns
        -------
        list of int
            The distinct, sorted repository IDs of conflicting pages. Pages
            belonging to ``repository_id`` itself, pages with no ID recorded
            yet, soft-deleted pages, and pull-request preview pages are all
            excluded.
        """
        statement = (
            select(SqlPage.github_repository_id)
            .where(SqlPage.github_owner == owner)
            .where(SqlPage.github_repo == name)
            .where(SqlPage.github_repository_id.is_not(None))
            .where(SqlPage.github_repository_id != repository_id)
            .where(SqlPage.date_deleted == None)  # noqa: E711
            .where(SqlPage.github_commit == None)  # noqa: E711
            .distinct()
        )
        result = await self._session.execute(statement)
        return sorted(row[0] for row in result.all())

    async def rename_repository(
        self,
        *,
        owner: str,
        old_name: str,
        new_name: str,
        repository_id: int | None = None,
    ) -> list[str]:
        """Flip the stored repository name on every page of a GitHub
        repository in a single statement.

        This is a pure name flip: no other column is touched, so the pages'
        notebooks, parameters, and cached renders are all left alone.

        Parameters
        ----------
        owner : str
            The login name of the repository owner. Only used by the
            name-keyed fallback.
        old_name : str
            The repository name the pages are stored under. Only used by the
            name-keyed fallback.
        new_name : str
            The repository name to store.
        repository_id : int, optional
            GitHub's stable numeric ID for the repository. When given, pages
            are matched on this ID — which survives renames — unioned with a
            match on ``owner``/``old_name`` restricted to pages that have no
            ID recorded yet.

        Returns
        -------
        list of str
            The names (URL slugs) of the pages that were renamed. Pages
            already stored under ``new_name`` are not matched, so a
            redelivered webhook reports an empty list.
        """
        name_match = and_(
            SqlPage.github_owner == owner, SqlPage.github_repo == old_name
        )
        if repository_id is None:
            repository_match = name_match
        else:
            repository_match = or_(
                SqlPage.github_repository_id == repository_id,
                and_(SqlPage.github_repository_id.is_(None), name_match),
            )
        statement = (
            update(SqlPage)
            .where(repository_match)
            .where(SqlPage.github_repo != new_name)
            .values(github_repo=new_name)
            .returning(SqlPage.name)
        )
        result = await self._session.execute(
            statement, execution_options={"synchronize_session": False}
        )
        return [row[0] for row in result.all()]

    async def rename_owner(
        self, *, old_login: str, new_login: str, owner_id: int
    ) -> list[str]:
        """Flip the stored owner login on every page of a GitHub owner in a
        single statement.

        This is a pure name flip: no other column is touched, so the pages'
        notebooks, parameters, and cached renders are all left alone.

        Parameters
        ----------
        old_login : str
            The login the pages are stored under. Only used by the name-keyed
            fallback.
        new_login : str
            The login to store.
        owner_id : int
            GitHub's stable numeric ID for the owner. Pages are matched on
            this ID — which survives renames — unioned with a match on
            ``old_login`` restricted to pages that have no owner ID recorded
            yet.

        Returns
        -------
        list of str
            The names (URL slugs) of the pages that were renamed. Pages
            already stored under ``new_login`` are not matched, so a
            redelivered webhook reports an empty list.
        """
        statement = (
            update(SqlPage)
            .where(
                or_(
                    SqlPage.github_owner_id == owner_id,
                    and_(
                        SqlPage.github_owner_id.is_(None),
                        SqlPage.github_owner == old_login,
                    ),
                )
            )
            .where(SqlPage.github_owner != new_login)
            .values(github_owner=new_login)
            .returning(SqlPage.name)
        )
        result = await self._session.execute(
            statement, execution_options={"synchronize_session": False}
        )
        return [row[0] for row in result.all()]

    async def transfer_repository(
        self,
        *,
        repository_id: int,
        new_owner: str,
        new_owner_id: int,
        new_name: str,
    ) -> list[str]:
        """Rewrite the stored owner, owner ID, and repository name on every
        page of a GitHub repository in a single statement.

        This is a pure identity flip: no other column is touched, so the
        pages' notebooks, parameters, and cached renders are all left alone.

        Unlike `rename_repository` this has **no** name-keyed fallback for
        pages that predate ID capture. A transfer frees the repository's old
        ``owner/repo`` name pair on GitHub the moment it happens, so a
        name-keyed match could rewrite the pages of whatever repository has
        since claimed that name. Un-backfilled pages are instead healed by
        the next sync of the repository.

        Parameters
        ----------
        repository_id : int
            GitHub's stable numeric ID for the repository. This is the only
            thing pages are matched on.
        new_owner : str
            The login name of the repository's new owner.
        new_owner_id : int
            GitHub's stable numeric ID for the new owner.
        new_name : str
            The repository's name under its new owner. GitHub allows a
            repository to be renamed as part of a transfer, so this is not
            necessarily the name the pages are stored under.

        Returns
        -------
        list of str
            The names (URL slugs) of the pages that were updated. Pages
            already stored under the new identity are not matched, so a
            redelivered webhook reports an empty list.
        """
        statement = (
            update(SqlPage)
            .where(SqlPage.github_repository_id == repository_id)
            .where(
                or_(
                    SqlPage.github_owner != new_owner,
                    SqlPage.github_repo != new_name,
                    SqlPage.github_owner_id.is_distinct_from(new_owner_id),
                )
            )
            .values(
                github_owner=new_owner,
                github_owner_id=new_owner_id,
                github_repo=new_name,
            )
            .returning(SqlPage.name)
        )
        result = await self._session.execute(
            statement, execution_options={"synchronize_session": False}
        )
        return [row[0] for row in result.all()]

    async def count_pages_missing_github_ids(
        self,
    ) -> dict[tuple[str, str], int]:
        """Tally the GitHub-backed pages that have no numeric repository ID
        recorded yet, grouped by the owner and repository names they are
        stored under.

        This is the work list for the ``backfill-github-ids`` command: each
        key is a repository whose identity has to be resolved from the GitHub
        API, and each value is how many pages that resolution would fill in.

        Soft-deleted pages and pull-request preview pages are included. Their
        numeric IDs are as much a part of their GitHub identity as any other
        page's, and grouping means they only cost an extra API call when no
        live page shares their repository.

        Returns
        -------
        dict
            A mapping from ``(owner, repository name)`` to the number of
            pages stored under those names with no repository ID. Ordered by
            owner and then repository name.
        """
        statement = (
            select(
                SqlPage.github_owner,
                SqlPage.github_repo,
                func.count().label("page_count"),
            )
            .where(SqlPage.github_owner.is_not(None))
            .where(SqlPage.github_repo.is_not(None))
            .where(SqlPage.github_repository_id.is_(None))
            .group_by(SqlPage.github_owner, SqlPage.github_repo)
            .order_by(SqlPage.github_owner, SqlPage.github_repo)
        )
        result = await self._session.execute(statement)
        return {(row[0], row[1]): row[2] for row in result.all()}

    async def backfill_github_ids(
        self,
        *,
        owner: str,
        name: str,
        repository_id: int,
        owner_id: int,
        installation_id: int,
    ) -> list[str]:
        """Record the numeric repository, owner, and installation IDs on the
        pages stored under an owner/repository name pair that have none.

        Pages that already carry a repository ID are left alone: their
        identity came from a sync, which is authoritative, whereas the IDs
        written here were resolved from name strings that may since have moved
        to another repository.

        Parameters
        ----------
        owner : str
            The login name of the repository owner the pages are stored under.
        name : str
            The repository name the pages are stored under.
        repository_id : int
            GitHub's stable numeric ID for the repository.
        owner_id : int
            GitHub's stable numeric ID for the repository owner.
        installation_id : int
            The numeric ID of the Times Square GitHub App installation that
            covers the repository.

        Returns
        -------
        list of str
            The names (URL slugs) of the pages that were filled in.
        """
        statement = (
            update(SqlPage)
            .where(SqlPage.github_owner == owner)
            .where(SqlPage.github_repo == name)
            .where(SqlPage.github_repository_id.is_(None))
            .values(
                github_repository_id=repository_id,
                github_owner_id=owner_id,
                github_installation_id=installation_id,
            )
            .returning(SqlPage.name)
        )
        result = await self._session.execute(
            statement, execution_options={"synchronize_session": False}
        )
        return [row[0] for row in result.all()]

    def _rehydrate_page_from_sql(self, sql_page: SqlPage) -> PageModel:
        """Create a page domain model from the SQL result."""
        parameters = PageParameters.create_and_validate(sql_page.parameters)

        date_deleted = (
            datetime_from_db(sql_page.date_deleted)
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
            timeout=sql_page.execution_timeout,
            schedule_rruleset=sql_page.schedule_rruleset,
            schedule_enabled=sql_page.schedule_enabled,
            uploader_username=sql_page.uploader_username,
            description=sql_page.description,
            cache_ttl=sql_page.cache_ttl,
            github_owner=sql_page.github_owner,
            github_repo=sql_page.github_repo,
            github_repository_id=sql_page.github_repository_id,
            github_owner_id=sql_page.github_owner_id,
            github_installation_id=sql_page.github_installation_id,
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

    async def list_page_summaries(self) -> list[PageSummaryModel]:
        """Get a listing of page summaries (excludes the ipynb and
        parameters).

        Rather than a list of `PageModel` objects, Times Square's page
        listing APIs generally need to just provide a listing of page titles
        and metadata that's useful or populating index UIs. That's why we're
        producing a list of `PageSummaryModel` objects here.
        """
        # Consider adding other fields like title, description,
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

    async def get_github_tree(self) -> list[GitHubNode]:
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

        nodes: list[GitHubNode] = []
        for owner_name in result.scalars():
            if owner_name is None:
                # This is a page that's not backed by GitHub; should already
                # be filtered out by the query above, but for typing.
                continue
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
    ) -> list[GitHubNode]:
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

    async def list_page_names(self) -> list[str]:
        """Get a list of all page names."""
        statement = select(SqlPage.name)
        result = await self._session.execute(statement)
        return [row[0] for row in result.all()]

    async def list_scheduled_pages(
        self, *, exclude_pr_pages: bool = True
    ) -> list[PageModel]:
        """Get a list of all pages with scheduling enabled."""
        statement = (
            select(SqlPage)
            .where(SqlPage.schedule_enabled.is_(True))
            .where(SqlPage.date_deleted.is_(None))
            .where(SqlPage.schedule_rruleset.is_not(None))
        )
        if exclude_pr_pages:
            statement = statement.where(SqlPage.github_commit.is_(None))
        result = await self._session.execute(statement)
        return [
            self._rehydrate_page_from_sql(sql_page)
            for sql_page in result.scalars()
        ]
