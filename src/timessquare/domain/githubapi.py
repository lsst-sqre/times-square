"""Pydantic models describing resources from the GitHub REST v3 API."""

from __future__ import annotations

from base64 import b64decode

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

    branches_url: str = Field(
        title="URI template for the repo's branches endpoint",
        example=(
            "https://github.com/lsst-sqre/times-square-demo/branches{/branch}"
        ),
    )

    contents_url: str = Field(
        title="URI template for the contents endpoint",
        example=(
            "https://github.com/lsst-sqre/times-square-demo/contents/{+path}"
        ),
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


class GitHubBranchCommitModel(BaseModel):
    """A Pydantic model for the commit field found in GitHubBranchModel."""

    sha: str = Field(title="Git commit SHA")

    url: HttpUrl = Field(title="URL for commit resource")


class GitHubBranchModel(BaseModel):
    """A Pydantic model for a GitHub branch.

    https://docs.github.com/en/rest/branches/branches#get-a-branch
    """

    name: str = Field(title="Branch name", example="main")

    commit: GitHubBranchCommitModel = Field(title="HEAD commit info")


class GitHubBlobModel(BaseModel):
    """A Pydantic model for a blob, returned the GitHub blob endpoint

    See https://docs.github.com/en/rest/git/blobs#get-a-blob
    """

    content: str = Field(title="Encoded content")

    encoding: str = Field(
        title="Content encoding", description="Typically is base64"
    )

    url: HttpUrl = Field(title="API url of this resource")

    sha: str = Field(title="Git sha of tree object")

    size: int = Field(title="Size of the content in bytes")

    def decode(self) -> str:
        """Decode content.

        Currently supports these encodings:

        - base64
        """
        if self.encoding == "base64":
            return b64decode(self.content).decode()
        else:
            raise NotImplementedError(
                f"GitHub blob content encoding {self.encoding} "
                f"is unknown by GitHubBlobModel for url {self.url}"
            )
