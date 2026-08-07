"""Service layer for healing drift between the GitHub owner and repository
names Times Square stores and the names GitHub answers with.
"""

from __future__ import annotations

from dataclasses import dataclass

from gidgethub import HTTPException
from safir.github import GitHubAppClientFactory
from structlog.stdlib import BoundLogger

from ..config import config
from ..storage.github.apimodels import GitHubRepositoryWithIdModel
from ..storage.page import PageStore, StoredGitHubRepository

__all__ = [
    "GitHubNameReconciliationReport",
    "GitHubNameReconciliationService",
]


@dataclass(frozen=True, slots=True)
class GitHubNameReconciliationReport:
    """A summary of one run of the GitHub name reconciliation."""

    repositories_checked: int
    """The number of repositories re-read from the GitHub API."""

    repositories_healed: int
    """The number of repositories whose stored names had drifted and were
    rewritten.
    """

    repositories_skipped: int
    """The number of repositories that have left Times Square's remit.

    Their current owner is not in
    `~timessquare.config.Config.accepted_github_orgs`, so their names are
    reported rather than healed.
    """

    repositories_failed: int
    """The number of repositories the GitHub App could not re-read.

    Their pages are left untouched: an authentication hiccup or a transient
    GitHub error must never be mistaken for a repository that has gone away.
    """

    pages_updated: int
    """The number of pages whose stored GitHub names were rewritten."""


class GitHubNameReconciliationService:
    """Heal drift between the GitHub owner and repository names Times Square
    stores on its pages and the names GitHub currently answers with.

    Times Square learns about renames and transfers from webhooks, and every
    repository sync refreshes the stored names, so the stored names are
    normally correct. Neither mechanism covers a rename that happens while
    Times Square is down, or one whose webhook delivery fails: those pages
    keep serving under names that no longer exist until the repository's next
    push. This service closes that gap by re-reading every repository behind a
    live page from the GitHub API — by its stable numeric ID, which no rename
    or transfer changes — and rewriting the stored names when they disagree.
    It is driven by the daily ``reconcile_github_names`` cron.

    A repository the GitHub App cannot read is only ever logged. A repository
    that has genuinely been deleted, and an installation token that could not
    be minted, are indistinguishable here, and destroying a repository's pages
    over a transient authentication failure is far worse than serving stale
    names for another day. Deletion stays with the webhooks that can tell the
    difference.

    Parameters
    ----------
    page_store
        The page storage layer.
    github_client_factory
        Factory for GitHub App clients. The reconciliation is not triggered by
        a webhook, so it authenticates as each repository's recorded App
        installation.
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

    async def reconcile(self) -> GitHubNameReconciliationReport:
        """Re-read every GitHub repository behind a live page and rewrite the
        owner and repository names stored on its pages if they have drifted.

        This is a pure name flip, exactly like the rename and transfer
        webhooks: no content is re-synced and no notebook is re-executed,
        because a rename changes none of the repository's bytes and the HTML
        cache is keyed on each page's own name slug.

        Returns
        -------
        GitHubNameReconciliationReport
            A summary of the run.

        Notes
        -----
        This does not commit; the caller is responsible for committing or
        rolling back.
        """
        healed = 0
        skipped = 0
        failed = 0
        pages_updated = 0
        stored_repositories = (
            await self._page_store.list_github_repository_identities()
        )
        for stored in stored_repositories:
            current = await self._fetch_repository(stored)
            if current is None:
                failed += 1
                continue
            if current.owner.login not in config.accepted_github_orgs:
                self._log_for(stored).warning(
                    "GitHub repository now belongs to an owner Times Square "
                    "does not sync from; leaving its pages under their "
                    "stored names",
                    current_github_owner=current.owner.login,
                    current_github_repo=current.name,
                    accepted_orgs=config.accepted_github_orgs,
                )
                skipped += 1
                continue
            page_names = await self._page_store.transfer_repository(
                repository_id=stored.repository_id,
                new_owner=current.owner.login,
                new_owner_id=current.owner.id,
                new_name=current.name,
            )
            if page_names:
                healed += 1
                pages_updated += len(page_names)
                self._log_for(stored).info(
                    "Healed drifted GitHub repository names",
                    current_github_owner=current.owner.login,
                    current_github_repo=current.name,
                    current_github_owner_id=current.owner.id,
                    page_count=len(page_names),
                    page_names=page_names,
                )
        return GitHubNameReconciliationReport(
            repositories_checked=len(stored_repositories),
            repositories_healed=healed,
            repositories_skipped=skipped,
            repositories_failed=failed,
            pages_updated=pages_updated,
        )

    async def _fetch_repository(
        self, stored: StoredGitHubRepository
    ) -> GitHubRepositoryWithIdModel | None:
        """Re-read a repository by its numeric ID, or return `None` if the
        GitHub App cannot read it.

        Reading by ID rather than by the stored ``owner/repo`` names is what
        makes the reconciliation work at all: those names are the very thing
        suspected of being stale.
        """
        try:
            installation_client = (
                await self._github_client_factory.create_installation_client(
                    stored.installation_id
                )
            )
            data = await installation_client.getitem(
                "/repositories/{repository_id}",
                url_vars={"repository_id": str(stored.repository_id)},
            )
        except HTTPException as e:
            self._log_for(stored).warning(
                "Could not re-read a GitHub repository; leaving its pages "
                "untouched",
                status_code=int(e.status_code),
            )
            return None
        return GitHubRepositoryWithIdModel.model_validate(data)

    def _log_for(self, stored: StoredGitHubRepository) -> BoundLogger:
        """Bind the stored identity of a repository to the logger."""
        return self._logger.bind(
            github_owner=stored.owner,
            github_repo=stored.name,
            github_repository_id=stored.repository_id,
            github_installation_id=stored.installation_id,
        )
