"""Service layer related to GitHub-backed content.

This service works with the githubcheckout domain models and collaborates
with the Page service for managing page domain models.
"""

from __future__ import annotations

from gidgethub.httpx import GitHubAPI
from structlog.stdlib import BoundLogger

from timessquare.domain.githubwebhook import (
    GitHubPullRequestModel,
    GitHubPushEventModel,
)

from ..page import PageService


class GitHubRepoService:
    """A service manager for GitHub-backed pages.

    Parameters
    ----------
    github_client : `GitHubAPI`
        A GidgetHub API client that is authenticated as a GitHub app
        installation.
    page_service : `PageService`
        The Page service. This GitHubRepoService acts as a layer on top of
        the regular page service to handle domain models from the github
        domain.
    logger : `BoundLogger`
        A logger, ideally with request/worker job context already bound.
    """

    def __init__(
        self,
        github_client: GitHubAPI,
        page_service: PageService,
        logger: BoundLogger,
    ) -> None:
        self._github_client = github_client
        self._page_service = page_service
        self._logger = logger

    async def sync_from_repo_installation(
        self,
        owner: str,
        repo_name: str,
    ) -> None:
        """Synchronize a new repository that was just installed."""
        pass

    async def sync_from_push(
        self,
        push_payload: GitHubPushEventModel,
    ) -> None:
        """Synchronize based on a GitHub push event."""
        pass

    async def delete_repository(self, owner: str, repo_name: str) -> None:
        """Run a soft-delete on all content from a GitHub repository.

        This service method is usually called when the GitHub App is
        uninstalled from a repository.
        """
        pass

    async def check_pull_request(
        self, pr_payload: GitHubPullRequestModel
    ) -> None:
        """Run a check on a pull request."""
        pass
