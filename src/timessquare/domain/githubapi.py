"""Pydantic models describing resources from the GitHub REST v3 API."""

from __future__ import annotations

from base64 import b64decode
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl

__all__ = [
    "GitHubRepoOwnerModel",
    "GitHubUserModel",
    "GitHubRepositoryModel",
    "GitHubPullState",
    "GitHubPullRequestModel",
    "GitHubBranchCommitModel",
    "GitHubBranchModel",
    "GitHubBlobModel",
    "GitHubCheckSuiteStatus",
    "GitHubCheckSuiteConclusion",
    "GitHubCheckSuiteModel",
    "GitHubCheckRunStatus",
    "GitHubCheckRunConclusion",
    "GitHubCheckRunAnnotationLevel",
    "GitHubCheckSuiteId",
    "GitHubCheckRunOutput",
    "GitHubCheckRunPrInfoModel",
    "GitHubCheckRunModel",
]


class GitHubRepoOwnerModel(BaseModel):
    """A Pydantic model for the "owner" field found in repository objects.

    https://docs.github.com/en/rest/repos/repos#get-a-repository
    """

    login: str = Field(
        title="Login name of the owner (either a user or an organization)"
    )


class GitHubUserModel(BaseModel):
    """A Pydantic model for the "user" field found in GitHub API resources.

    This contains brief (public) info about a user.
    """

    login: str = Field(title="Login name", description="GitHub username")

    html_url: HttpUrl = Field(description="Homepage for the user on GitHub")

    url: HttpUrl = Field(
        description="URL for the user's resource in the GitHub API"
    )

    avatar_url: HttpUrl = Field(description="URL to the user's avatar")


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

    blobs_url: str = Field(
        title="URI template for the Git blobs API",
        example=(
            "https://github.com/lsst-sqre/times-square-demo/git/blobs{/sha}"
        ),
    )


class GitHubPullState(str, Enum):
    """The state of a GitHub PR.

    https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
    """

    open = "open"
    closed = "closed"


class GitHubPullRequestModel(BaseModel):
    """A Pydantic model for a GitHub Pull Request.

    This is also the ``pull_request`` field inside the
    GitHubPullRequestEventModel.

    https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
    """

    html_url: HttpUrl = Field(title="Web URL of the PR")

    number: int = Field(title="Pull request number")

    title: str = Field(title="Title")

    state: GitHubPullState = Field(
        description="Whether the PR is opened or closed"
    )

    draft: bool = Field(description="True if the PR is a draft")

    merged: bool = Field(description="True if the PR is merged")

    user: GitHubUserModel = Field(description="The user that opened the PR")


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


class GitHubCheckSuiteStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"


class GitHubCheckSuiteConclusion(str, Enum):
    success = "success"
    failure = "failure"
    neutral = "neutral"
    cancelled = "cancelled"
    timed_out = "timed_out"
    action_required = "action_required"
    stale = "stale"


class GitHubCheckSuiteModel(BaseModel):
    """A Pydantic model for the "check_suite" field in a check_suite webhook
    (`GitHubCheckSuiteRequestModel`).
    """

    id: str = Field(description="Identifier for this check run")

    head_branch: str = Field(
        title="Head branch",
        description="Name of the branch the changes are on.",
    )

    head_sha: str = Field(
        title="Head sha",
        description="The SHA of the most recent commit for this check suite.",
    )

    url: HttpUrl = Field(
        description="GitHub API URL for the check suite resource."
    )

    status: GitHubCheckSuiteStatus

    conclusion: Optional[GitHubCheckSuiteConclusion]


class GitHubCheckRunStatus(str, Enum):
    """The check run status."""

    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"


class GitHubCheckRunConclusion(str, Enum):
    """The check run conclusion state."""

    success = "success"
    failure = "failure"
    neutral = "neutral"
    cancelled = "cancelled"
    timed_out = "timed_out"
    action_required = "action_required"
    stale = "stale"


class GitHubCheckRunAnnotationLevel(str, Enum):
    """The level of a check run output annotation."""

    notice = "notice"
    warning = "warning"
    failure = "failure"


class GitHubCheckSuiteId(BaseModel):
    """Brief information about a check suite in the `GitHubCheckRunModel`."""

    id: str = Field(description="Check suite ID")


class GitHubCheckRunOutput(BaseModel):
    """Check run output report."""

    title: Optional[str] = Field(None, description="Title of the report")

    summary: Optional[str] = Field(
        None, description="Summary information (markdown formatted"
    )

    text: Optional[str] = Field(None, description="Extended report (markdown)")


class GitHubCheckRunPrInfoModel(BaseModel):
    """A Pydantic model of the "pull_requsts[]" items in a check run
    GitHub API model.

    https://docs.github.com/en/rest/checks/runs#get-a-check-run
    """

    url: HttpUrl = Field(description="GitHub API URL for this pull request")


class GitHubCheckRunModel(BaseModel):
    """A Pydantic model for the "check_run" field in a check_run webhook
    payload (`GitHubCheckRunPayloadModel`).
    """

    id: str = Field(description="Identifier for this check run")

    external_id: Optional[str] = Field(
        description="Identifier set by the check runner."
    )

    head_sha: str = Field(
        title="Head sha",
        description="The SHA of the most recent commit for this check suite.",
    )

    status: GitHubCheckRunStatus = Field(
        description="Status of the check run."
    )

    conclusion: Optional[GitHubCheckRunConclusion] = Field(
        description="Conclusion status, if completed."
    )

    name: str = Field(description="Name of the check run.")

    url: HttpUrl = Field(description="URL of the check run API resource.")

    html_url: HttpUrl = Field(description="URL of the check run webpage.")

    check_suite: GitHubCheckSuiteId

    output: Optional[GitHubCheckRunOutput] = Field(
        None, title="Output", description="Check run output, if available."
    )

    pull_requests: List[GitHubCheckRunPrInfoModel] = Field(
        default_factory=list
    )
