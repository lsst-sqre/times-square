"""Service layer related to GitHub-backed content.

This service works with the githubcheckout domain models and collaborates
with the Page service for managing page domain models.
"""

from __future__ import annotations

from gidgethub.httpx import GitHubAPI
from structlog.stdlib import BoundLogger

from timessquare.domain.githubapi import (
    GitHubBlobModel,
    GitHubBranchModel,
    GitHubRepositoryModel,
)
from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositorySettingsFile,
)
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
        repo = await self.request_github_repository(owner, repo_name)
        branch = await self.request_github_branch(
            url_template=repo.branches_url, branch=repo.default_branch
        )
        checkout = await self.create_checkout(
            repo=repo,
            git_ref=f"refs/heads/{branch.name}",
            head_sha=branch.commit.sha,
        )
        await self.sync_checkout(checkout)

    async def sync_from_push(
        self,
        push_payload: GitHubPushEventModel,
    ) -> None:
        """Synchronize based on a GitHub push event."""
        checkout = await self.create_checkout(
            repo=push_payload.repository,
            git_ref=push_payload.ref,
            head_sha=push_payload.after,
        )
        await self.sync_checkout(checkout)

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

    async def request_github_repository(
        self, owner: str, repo: str
    ) -> GitHubRepositoryModel:
        """Request the GitHub repo resource from the GitHub API."""
        uri = "/repos/{owner}/{repo}"
        data = await self._github_client.getitem(
            uri, url_vars={"owner": owner, "repo": repo}
        )
        return GitHubRepositoryModel.parse_obj(data)

    async def request_github_branch(
        self, *, url_template: str, branch: str
    ) -> GitHubBranchModel:
        """Request a GitHub branch resource."""
        data = await self._github_client.getitem(
            url_template, url_vars={"branch": branch}
        )
        return GitHubBranchModel.parse_obj(data)

    async def create_checkout(
        self, *, repo: GitHubRepositoryModel, git_ref: str, head_sha: str
    ) -> GitHubRepositoryCheckout:
        settings = await self.load_settings_file(repo=repo, git_ref=head_sha)
        checkout = GitHubRepositoryCheckout(
            owner_name=repo.owner.login,
            name=repo.name,
            settings=settings,
            git_ref=git_ref,
            head_sha=head_sha,
            trees_url=repo.trees_url,
        )
        return checkout

    async def load_settings_file(
        self, *, repo: GitHubRepositoryModel, git_ref: str
    ) -> RepositorySettingsFile:
        """Load the times-square.yaml from a repository."""
        uri = repo.contents_url + "{?ref}"
        # TODO handle cases where the repo doesn't have settings (i.e.
        # fail gracefully)
        data = await self._github_client.getitem(
            uri, url_vars={"path": "times-square.yaml", "ref": git_ref}
        )
        content_data = GitHubBlobModel.parse_obj(data)
        file_content = content_data.decode()
        return RepositorySettingsFile.parse_raw(file_content)

    async def sync_checkout(self, checkout: GitHubRepositoryCheckout) -> None:
        """Sync a "checkout" of a GitHub repository."""
        pass
