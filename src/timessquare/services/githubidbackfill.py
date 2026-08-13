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


@dataclass(frozen=True, slots=True)
class _ResolvedRepository:
    """One repository the GitHub App resolved, ready to be written."""

    owner: str
    """The owner login the pages are stored under."""

    name: str
    """The repository name the pages are stored under."""

    page_count: int
    """The number of pages stored under those names with no repository ID."""

    identity: _RepositoryIdentity
    """The numeric identity GitHub answered with."""


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

        Warnings
        --------
        Resolution is by name, which is exactly the identity a rename
        invalidates, so the backfill is only as trustworthy as the stored
        names. A repository the App cannot see is skipped, but a stored name
        that has since been *claimed by a different repository* the App can
        see resolves successfully and stamps the wrong repository's IDs onto
        the pages — after which the ID-keyed rename handling rewrites them
        into that repository in earnest. Nothing in a by-name lookup can
        distinguish the two cases. Keep the window short: run the backfill
        promptly after deploying, and read the ``--dry-run`` report first.

        Notes
        -----
        This does not commit; the caller is responsible for committing or
        rolling back.

        Every GitHub round trip is made before the first row is written, so
        that the row locks the bulk updates take are held for one short burst
        at the end rather than across every remaining repository's round
        trip.
        """
        tally = await self._page_store.count_pages_missing_github_ids()
        resolutions, skipped = await self._resolve_all(tally)

        pages_updated = 0
        for resolution in resolutions:
            identity = resolution.identity
            if dry_run:
                pages_updated += resolution.page_count
            else:
                backfilled = await self._page_store.backfill_github_ids(
                    owner=resolution.owner,
                    name=resolution.name,
                    repository_id=identity.repository_id,
                    owner_id=identity.owner_id,
                    installation_id=identity.installation_id,
                )
                pages_updated += len(backfilled)
            self._logger.info(
                "Resolved GitHub IDs for repository",
                github_owner=resolution.owner,
                github_repo=resolution.name,
                github_repository_id=identity.repository_id,
                github_owner_id=identity.owner_id,
                github_installation_id=identity.installation_id,
                page_count=resolution.page_count,
                dry_run=dry_run,
            )
        return GitHubIdBackfillReport(
            dry_run=dry_run,
            repositories_resolved=len(resolutions),
            repositories_skipped=skipped,
            pages_updated=pages_updated,
        )

    async def _resolve_all(
        self, tally: dict[tuple[str, str], int]
    ) -> tuple[list[_ResolvedRepository], int]:
        """Resolve every repository in the work list through the GitHub API,
        without writing anything.

        Returns
        -------
        tuple
            The repositories that resolved, and the number that did not.
        """
        resolutions = []
        skipped = 0
        for (owner, name), page_count in tally.items():
            identity = await self._resolve_repository(owner=owner, name=name)
            if identity is None:
                skipped += 1
                continue
            resolutions.append(
                _ResolvedRepository(
                    owner=owner,
                    name=name,
                    page_count=page_count,
                    identity=identity,
                )
            )
        return resolutions, skipped

    async def _resolve_repository(
        self, *, owner: str, name: str
    ) -> _RepositoryIdentity | None:
        """Resolve a repository's numeric identity from its stored names, or
        return `None` if the GitHub App cannot see it.

        The names are taken at face value. If the repository they used to
        name has been renamed away and another App-visible repository has
        claimed the pair since, this answers with that repository's identity
        instead — see the warning on `backfill`.
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
