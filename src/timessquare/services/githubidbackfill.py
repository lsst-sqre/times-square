"""Service layer for backfilling GitHub's stable numeric IDs onto pages that
predate ID capture.
"""

from __future__ import annotations

from dataclasses import dataclass

from gidgethub import HTTPException
from safir.github import GitHubAppClientFactory
from structlog.stdlib import BoundLogger

from ..storage.github.apimodels import GitHubRepositoryWithIdModel
from ..storage.page import PageStore

__all__ = ["GitHubIdBackfillReport", "GitHubIdBackfillService"]


@dataclass(frozen=True, slots=True)
class GitHubIdBackfillReport:
    """A summary of one run of the GitHub numeric ID backfill."""

    dry_run: bool
    """Whether the run reported its work instead of doing it."""

    repositories_resolved: int
    """The number of repositories whose identity the GitHub App resolved."""

    repositories_skipped: int
    """The number of repositories the GitHub App could not resolve.

    Their pages keep their null IDs, and are matched by name until a sync or
    a later backfill fills them in.
    """

    pages_updated: int
    """The number of pages whose numeric IDs were filled in, or in a dry run,
    would have been filled in.
    """


@dataclass(frozen=True, slots=True)
class _RepositoryIdentity:
    """The numeric identity of one GitHub repository."""

    repository_id: int
    owner_id: int
    installation_id: int


class GitHubIdBackfillService:
    """Fill in the numeric GitHub IDs of pages created before Times Square
    started recording them.

    Repository syncs record the numeric repository, owner, and installation
    IDs on the pages they touch, so pages heal themselves over time. This
    service does the same job in one pass over the whole database, so that
    renames are handled by ID from the start rather than only after each
    repository's next push. It is driven by the ``backfill-github-ids``
    command and is expected to be run once, as a Kubernetes job.

    Parameters
    ----------
    page_store
        The page storage layer.
    github_client_factory
        Factory for GitHub App clients. The backfill is not triggered by a
        webhook, so it has no installation to authenticate as up front and
        resolves one per repository.
    logger
        A logger.
    """

    def __init__(
        self,
        *,
        page_store: PageStore,
        github_client_factory: GitHubAppClientFactory,
        logger: BoundLogger,
    ) -> None:
        self._page_store = page_store
        self._github_client_factory = github_client_factory
        self._logger = logger

    async def backfill(
        self, *, dry_run: bool = False
    ) -> GitHubIdBackfillReport:
        """Record the numeric GitHub IDs on every GitHub-backed page that has
        none.

        Each distinct ``owner/repository`` name pair costs one resolution
        against the GitHub API, and repositories the GitHub App cannot see —
        because they were deleted, made private, or renamed out from under
        the stored names — are logged and skipped without failing the run.

        Parameters
        ----------
        dry_run
            If `True`, resolve every repository and report the pages that
            would be filled in without writing anything.

        Returns
        -------
        GitHubIdBackfillReport
            A summary of the run.

        Notes
        -----
        This does not commit; the caller is responsible for committing or
        rolling back.
        """
        tally = await self._page_store.count_pages_missing_github_ids()
        resolved = 0
        skipped = 0
        pages_updated = 0
        for (owner, name), page_count in tally.items():
            identity = await self._resolve_repository(owner=owner, name=name)
            if identity is None:
                skipped += 1
                continue
            resolved += 1
            if dry_run:
                pages_updated += page_count
            else:
                backfilled = await self._page_store.backfill_github_ids(
                    owner=owner,
                    name=name,
                    repository_id=identity.repository_id,
                    owner_id=identity.owner_id,
                    installation_id=identity.installation_id,
                )
                pages_updated += len(backfilled)
            self._logger.info(
                "Resolved GitHub IDs for repository",
                github_owner=owner,
                github_repo=name,
                github_repository_id=identity.repository_id,
                github_owner_id=identity.owner_id,
                github_installation_id=identity.installation_id,
                page_count=page_count,
                dry_run=dry_run,
            )
        return GitHubIdBackfillReport(
            dry_run=dry_run,
            repositories_resolved=resolved,
            repositories_skipped=skipped,
            pages_updated=pages_updated,
        )

    async def _resolve_repository(
        self, *, owner: str, name: str
    ) -> _RepositoryIdentity | None:
        """Resolve a repository's numeric identity from its stored names, or
        return `None` if the GitHub App cannot see it.
        """
        try:
            installation_id = await self._request_installation_id(
                owner=owner, name=name
            )
            installation_client = (
                await self._github_client_factory.create_installation_client(
                    installation_id
                )
            )
            data = await installation_client.getitem(
                "/repos/{owner}/{repo}",
                url_vars={"owner": owner, "repo": name},
            )
        except HTTPException as e:
            self._logger.warning(
                "Skipping a repository the GitHub App cannot resolve",
                github_owner=owner,
                github_repo=name,
                status_code=int(e.status_code),
            )
            return None
        repository = GitHubRepositoryWithIdModel.model_validate(data)
        return _RepositoryIdentity(
            repository_id=repository.id,
            owner_id=repository.owner.id,
            installation_id=installation_id,
        )

    async def _request_installation_id(self, *, owner: str, name: str) -> int:
        """Get the ID of the GitHub App installation covering a repository."""
        anonymous_client = (
            self._github_client_factory.create_anonymous_client()
        )
        data = await anonymous_client.getitem(
            "/repos/{owner}/{repo}/installation",
            url_vars={"owner": owner, "repo": name},
            jwt=self._github_client_factory.get_app_jwt(),
        )
        return int(data["id"])
