"""Domain models related to payloads from GitHub webhook events.

These Pydantic models are designed to capture relevant subsets of data from
GitHub webhook payloads.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class GitHubRepoOwnerModel(BaseModel):
    """A Pydantic model for the "owner" field found in repository objects.

    https://docs.github.com/en/rest/repos/repos#get-a-repository
    """

    login: str = Field(
        title="Login name of the owner (either a user or an organization)"
    )


class GitHubRepositoryModel(BaseModel):
    """A Pydantic model for the "repository" field, often found in webhook
    payloads.

    https://docs.github.com/en/rest/repos/repos#get-a-repository
    """

    name: str = Field(
        title="Repository name",
        description="Excludes owner prefix.",
        example="times-square-demo",
    )

    full_name: str = Field(
        title="Full name",
        description="Includes owner prefix",
        example="lsst-sqre/times-square-demo",
    )

    owner: GitHubRepoOwnerModel = Field(title="The repository's owner")

    default_branch: str = Field(title="The default branch", example="main")

    html_url: HttpUrl = Field(
        title="URL of the repository for browsers",
        example="https://github.com/lsst-sqre/times-square-demo",
    )

    trees_url: str = Field(
        title="URI template for the Git tree API",
        example=(
            "https://github.com/lsst-sqre/times-square-demo/git/trees{/sha}"
        ),
    )


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
