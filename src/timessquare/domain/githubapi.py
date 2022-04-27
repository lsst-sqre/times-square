"""Pydantic models describing resources from the GitHub REST v3 API."""

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


class GitHubPullRequestModel(BaseModel):
    """A Pydantic model for a GitHub Pull Request.

    This is also the ``pull_request`` field inside the
    GitHubPullRequestEventModel.

    https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
    """

    html_url: HttpUrl = Field(title="Web URL of the PR")

    number: int = Field(title="Pull request number")

    title: str = Field(title="Title")

    # TODO a lot more data is available. Expand this model as needed.
