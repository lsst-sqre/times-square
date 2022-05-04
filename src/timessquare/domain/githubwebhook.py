"""Domain models related to payloads from GitHub webhook events.

These Pydantic models are designed to capture relevant subsets of data from
GitHub webhook payloads.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from .githubapi import GitHubPullRequestModel, GitHubRepositoryModel


class GitHubAppInstallationModel(BaseModel):
    """A Pydantic model for the "installation" field found in webhook payloads
    for GitHub Apps.
    """

    id: str = Field(title="Installation ID")


class GitHubPushEventModel(BaseModel):
    """A Pydantic model for the push event webhook."""

    repository: GitHubRepositoryModel

    installation: GitHubAppInstallationModel

    ref: str = Field(
        title="The full git_ref that was pushed.",
        description=(
            "The full git ref that was pushed. Example: refs/heads/main or "
            "refs/tags/v3.14.1."
        ),
        example="refs/heads/main",
    )

    before: str = Field(
        title="The SHA of the most recent commit on ref before the push."
    )

    after: str = Field(
        title="The SHA of the most recent commit on ref after the push."
    )


class AppInstallationRepoModel(BaseModel):
    """A pydantic model for repository objects used by
    `GitHubAppInstallationRepositoriesEventModel`.
    """

    name: str

    full_name: str

    @property
    def owner_name(self) -> str:
        return self.full_name.split("/")[0]


class GitHubAppInstallationEventModel(BaseModel):
    """A Pydantic model for an "installation" webhook.

    https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads#installation
    """

    action: str = Field(
        title="Action performed", description="Either 'added' or 'removed'."
    )

    repositories: List[AppInstallationRepoModel] = Field(
        title="Repositories accessible to this installation"
    )

    installation: GitHubAppInstallationModel


class GitHubAppInstallationRepositoriesEventModel(BaseModel):
    """A Pydantic model for a "installation_repositories" webhook.

    https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads#installation_repositories
    """

    action: str = Field(
        title="Action performed", description="Either 'added' or 'removed'."
    )

    repositories_added: List[AppInstallationRepoModel] = Field(
        title="Repositories added"
    )

    repositories_removed: List[AppInstallationRepoModel] = Field(
        title="Repositories removed"
    )

    installation: GitHubAppInstallationModel


class GitHubPullRequestEventModel(BaseModel):
    """A Pydantic model for a "pull_request" webhook.

    https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads#pull_request
    """

    repository: GitHubRepositoryModel

    installation: GitHubAppInstallationModel

    action: str = Field(
        title="The action that was performed.",
        description=(
            "Many event types are possible. The most relevant to Times Square "
            "are ``opened`` and ``synchronize`` (when the head branch is "
            "updated)."
        ),
    )

    number: int = Field(title="Pull request number")

    pull_request: GitHubPullRequestModel
