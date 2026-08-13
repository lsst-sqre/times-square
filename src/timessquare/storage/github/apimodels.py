"""GitHub API models."""

# Most Pydantic models for GitHub are available through the safir package.
# These are additional models specific to Times Square's usage, and could be
# migrated to Safir in the future.

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl
from safir.github.models import GitHubRepoOwnerModel, GitHubRepositoryModel
from safir.github.webhooks import (
    GitHubAppInstallationModel,
    GitHubPushEventModel,
)

__all__ = [
    "GitHubInstallationTargetChangesModel",
    "GitHubInstallationTargetLoginChangeModel",
    "GitHubInstallationTargetRenamedEventModel",
    "GitHubPushEventWithIdModel",
    "GitHubRepoOwnerWithIdModel",
    "GitHubRepositoryChangesModel",
    "GitHubRepositoryNameChangeModel",
    "GitHubRepositoryOwnerChangeModel",
    "GitHubRepositoryPreviousOwnerModel",
    "GitHubRepositoryRenameChangesModel",
    "GitHubRepositoryRenamedEventModel",
    "GitHubRepositoryTransferChangesModel",
    "GitHubRepositoryTransferredEventModel",
    "GitHubRepositoryWithIdModel",
    "GitTreeItem",
    "GitTreeMode",
    "RecursiveGitTreeModel",
]


class GitHubRepoOwnerWithIdModel(GitHubRepoOwnerModel):
    """A repository owner that retains GitHub's stable numeric ID.

    Safir's `~safir.github.models.GitHubRepoOwnerModel` only parses the
    owner's ``login``, which changes when an organization or user is renamed.
    """

    id: Annotated[
        int,
        Field(
            title="Numeric ID",
            description=(
                "GitHub's stable numeric ID for the owner, which is "
                "unaffected by renames."
            ),
        ),
    ]


class GitHubRepositoryWithIdModel(GitHubRepositoryModel):
    """A repository that retains GitHub's stable numeric IDs for both the
    repository and its owner.

    Safir's `~safir.github.models.GitHubRepositoryModel` only parses the
    ``name``/``full_name`` strings, which change when a repository is renamed
    or transferred.
    """

    id: Annotated[
        int,
        Field(
            title="Numeric ID",
            description=(
                "GitHub's stable numeric ID for the repository, which is "
                "unaffected by renames and transfers."
            ),
        ),
    ]

    owner: Annotated[
        GitHubRepoOwnerWithIdModel,
        Field(description="The repository's owner, including its numeric ID."),
    ]


class GitHubPushEventWithIdModel(GitHubPushEventModel):
    """A ``push`` webhook payload that retains the numeric repository and
    owner IDs.

    Times Square validates push payloads with this model so that
    `~timessquare.services.githubrepo.GitHubRepoService` can record the
    stable IDs on the repository's pages.
    """

    repository: Annotated[
        GitHubRepositoryWithIdModel,
        Field(
            description=(
                "The repository that was pushed to, including numeric IDs."
            )
        ),
    ]


class GitHubRepositoryNameChangeModel(BaseModel):
    """The ``changes.repository.name`` object of a ``repository`` (renamed)
    webhook payload.
    """

    previous: Annotated[
        str,
        Field(
            alias="from",
            description="The repository's name before the rename.",
        ),
    ]


class GitHubRepositoryChangesModel(BaseModel):
    """The ``changes.repository`` object of a ``repository`` (renamed)
    webhook payload.
    """

    name: Annotated[
        GitHubRepositoryNameChangeModel,
        Field(description="The repository name's previous value."),
    ]


class GitHubRepositoryRenameChangesModel(BaseModel):
    """The ``changes`` object of a ``repository`` (renamed) webhook
    payload.
    """

    repository: Annotated[
        GitHubRepositoryChangesModel,
        Field(description="The repository fields that changed."),
    ]


class GitHubRepositoryRenamedEventModel(BaseModel):
    """A ``repository`` (renamed) webhook payload.

    https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository

    The ``repository`` field already carries the new name; the old name — the
    name Times Square's pages are still stored under — is only available from
    ``changes.repository.name.from``.
    """

    changes: Annotated[
        GitHubRepositoryRenameChangesModel,
        Field(description="The fields that changed in this event."),
    ]

    repository: Annotated[
        GitHubRepositoryWithIdModel,
        Field(
            description=(
                "The renamed repository, under its new name, including "
                "numeric IDs."
            )
        ),
    ]

    installation: Annotated[
        GitHubAppInstallationModel,
        Field(description="Information about the GitHub App installation."),
    ]

    @property
    def old_repo_name(self) -> str:
        """The repository's name before the rename."""
        return self.changes.repository.name.previous


class GitHubRepositoryPreviousOwnerModel(BaseModel):
    """The ``changes.owner.from`` object of a ``repository`` (transferred)
    webhook payload.

    GitHub reports the previous owner under ``organization`` or ``user``
    depending on what kind of account the repository came from, and only ever
    sends one of them.
    """

    organization: Annotated[
        GitHubRepoOwnerWithIdModel | None,
        Field(
            default=None,
            description="The organization the repository was transferred "
            "from, if it came from an organization.",
        ),
    ]

    user: Annotated[
        GitHubRepoOwnerWithIdModel | None,
        Field(
            default=None,
            description="The user the repository was transferred from, if it "
            "came from a user account.",
        ),
    ]

    @property
    def login(self) -> str | None:
        """The previous owner's login, whichever kind of account it was."""
        owner = self.organization or self.user
        return owner.login if owner else None


class GitHubRepositoryOwnerChangeModel(BaseModel):
    """The ``changes.owner`` object of a ``repository`` (transferred) webhook
    payload.
    """

    previous: Annotated[
        GitHubRepositoryPreviousOwnerModel,
        Field(
            alias="from",
            description="The owner the repository was transferred from.",
        ),
    ]


class GitHubRepositoryTransferChangesModel(BaseModel):
    """The ``changes`` object of a ``repository`` (transferred) webhook
    payload.
    """

    owner: Annotated[
        GitHubRepositoryOwnerChangeModel,
        Field(description="The repository owner's previous value."),
    ]


class GitHubRepositoryTransferredEventModel(BaseModel):
    """A ``repository`` (transferred) webhook payload.

    https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository

    The ``repository`` field carries the repository under its new owner, and
    possibly under a new name too, since GitHub allows a repository to be
    renamed as part of a transfer. Only the repository's numeric ID is
    unchanged, which is why the pages of a transferred repository are matched
    on that ID alone.
    """

    changes: Annotated[
        GitHubRepositoryTransferChangesModel,
        Field(description="The fields that changed in this event."),
    ]

    repository: Annotated[
        GitHubRepositoryWithIdModel,
        Field(
            description=(
                "The transferred repository, under its new owner, including "
                "numeric IDs."
            )
        ),
    ]

    installation: Annotated[
        GitHubAppInstallationModel,
        Field(description="Information about the GitHub App installation."),
    ]

    @property
    def old_owner_login(self) -> str | None:
        """The login of the owner the repository was transferred from.

        This is reported for operators, not used for matching pages: a
        transfer frees the old ``owner/repo`` name pair immediately, so
        matching on it risks catching another repository's pages.
        """
        return self.changes.owner.previous.login


class GitHubInstallationTargetLoginChangeModel(BaseModel):
    """The ``changes.login`` object of an ``installation_target`` (renamed)
    webhook payload.
    """

    previous: Annotated[
        str,
        Field(
            alias="from",
            description="The account's login before the rename.",
        ),
    ]


class GitHubInstallationTargetChangesModel(BaseModel):
    """The ``changes`` object of an ``installation_target`` (renamed) webhook
    payload.
    """

    login: Annotated[
        GitHubInstallationTargetLoginChangeModel | None,
        Field(
            default=None,
            description=(
                "The account login's previous value. GitHub does not mark "
                "this field as required, so a payload that renames something "
                "other than the login carries no old login to rename pages "
                "from."
            ),
        ),
    ]


class GitHubInstallationTargetRenamedEventModel(BaseModel):
    """An ``installation_target`` (renamed) webhook payload.

    https://docs.github.com/en/webhooks/webhook-events-and-payloads#installation_target

    GitHub sends this event when the user or organization account a GitHub App
    is installed on is renamed. Times Square uses it in preference to the
    ``organization`` event, which reports the same rename but is gated behind
    the Members organization permission and never fires for a personal
    account.

    The ``account`` field already carries the new login; the old login — the
    login Times Square's pages are still stored under — is only available from
    ``changes.login.from``.
    """

    changes: Annotated[
        GitHubInstallationTargetChangesModel,
        Field(description="The fields that changed in this event."),
    ]

    account: Annotated[
        GitHubRepoOwnerWithIdModel,
        Field(
            description=(
                "The renamed account, under its new login, including its "
                "numeric ID. An account payload carries the same ``login`` "
                "and ``id`` fields as a repository owner, so the owner model "
                "parses it too."
            )
        ),
    ]

    target_type: Annotated[
        str,
        Field(
            description=(
                "The kind of account that was renamed, ``Organization`` or "
                "``User``. Times Square treats both the same way — either is "
                "the ``github_owner`` of its pages — and records it only for "
                "operators reading the logs."
            )
        ),
    ]

    installation: Annotated[
        GitHubAppInstallationModel,
        Field(description="Information about the GitHub App installation."),
    ]

    @property
    def old_login(self) -> str | None:
        """The account's login before the rename, or `None` if the payload
        reports no login change.
        """
        if self.changes.login is None:
            return None
        return self.changes.login.previous

    @property
    def new_login(self) -> str:
        """The account's login after the rename."""
        return self.account.login


class GitTreeMode(StrEnum):
    """Git tree mode values."""

    file = "100644"
    executable = "100755"
    directory = "040000"
    submodule = "160000"
    symlink = "120000"


class GitTreeItem(BaseModel):
    """A Pydantic model for a single item in the response parsed by
    `RecursiveGitTreeModel`.
    """

    path: Annotated[str, Field(title="Path to the item in the repository")]

    mode: Annotated[GitTreeMode, Field(title="Mode of the item.")]

    sha: Annotated[str, Field(title="Git sha of tree object")]

    url: Annotated[HttpUrl, Field(title="URL of the object")]

    def match_glob(self, pattern: str) -> bool:
        """Test if this path matches a glob pattern."""
        p = PurePosixPath(self.path)
        return p.match(pattern)

    @property
    def path_extension(self) -> str:
        p = PurePosixPath(self.path)
        return p.suffix

    @property
    def path_stem(self) -> str:
        """The filepath, without the suffix."""
        return self.path[: -len(self.path_extension)]


class RecursiveGitTreeModel(BaseModel):
    """A Pydantic model for the output of ``GET api.github.com/repos/{owner}/
    {repo}/git/trees/{sha}?recursive=1`` for a git commit, which describes
    the full contents of a GitHub repository.
    """

    sha: Annotated[str, Field(title="SHA of the commit.")]

    url: Annotated[HttpUrl, Field(title="GitHub API URL of this resource")]

    tree: Annotated[list[GitTreeItem], Field(title="Items in the git tree")]

    truncated: Annotated[
        bool,
        Field(title="True if the dataset does not contain the whole repo"),
    ]
