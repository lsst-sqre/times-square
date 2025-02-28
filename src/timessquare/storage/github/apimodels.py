"""GitHub API models."""

# Most Pydantic models for GitHub are available through the safir package.
# These are additional models specific to Times Square's usage, and could be
# migrated to Safir in the future.

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl

__all__ = [
    "GitTreeItem",
    "GitTreeMode",
    "RecursiveGitTreeModel",
]


class GitTreeMode(str, Enum):
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
