"""Domain model for GitHub holdings as a hierarchical tree."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class GitHubNodeType(str, Enum):
    """Node type enumeration."""

    owner = "owner"
    """Owner is an organization or user."""

    repo = "repo"
    """GitHub repository."""

    directory = "directory"
    """Directory inside a GitHub repository."""

    page = "page"
    """Page inside a GitHub repository."""


class GitHubNode(BaseModel):
    """A node in the GitHub contents tree."""

    node_type: GitHubNodeType = Field(
        title="Node type",
        description=(
            "Indicates whether this a GitHub owner (user or organization), "
            "repository, directory in a repositiory, or a page itself."
        ),
    )

    title: str = Field(title="Display title")

    path: str = Field(
        title="Hierarchical path",
        description=(
            "The page is POSIX-path formatted without a preceeding or "
            "trailing slash. The first path element is always the owner, "
            "followed by the repository name, directory, and page name as "
            "necessary."
        ),
        example="lsst-sqre/times-square-demo/matplotlib/gaussian2d",
    )

    contents: List[GitHubNode] = Field(
        title="Nodes contained within this node.",
        description="For 'page' nodes, this is an empty list.",
        default_factory=list,
    )

    @property
    def path_segments(self) -> List[str]:
        return self.path.split("/")

    def insert_input(self, tree_input: GitHubTreeInput) -> None:
        n = len(self.path_segments)
        if n == len(tree_input.path_segments):
            # input is a direct child of this node
            self.contents.append(tree_input.to_node())
        else:
            # find child that contains input
            for child in self.contents:
                if (len(child.path_segments) >= n + 1) and (
                    child.path_segments[n] == tree_input.path_segments[n]
                ):
                    child.insert_input(tree_input)
                    return
            # Create a new child node because the necessary one doesn't
            # exist
            if n == 1:
                node_type = GitHubNodeType.repo
            else:
                node_type = GitHubNodeType.directory
            child = GitHubNode(
                node_type=node_type,
                title=tree_input.path_segments[n],
                path="/".join(tree_input.path_segments[: n + 1]),
                contents=[],
            )
            child.insert_input(tree_input)
            self.contents.append(child)


@dataclass
class GitHubTreeInput:
    """A domain class used to aid construction of the GitHub contents tree
    from the original SQL storage of pages.

    This class is used by `PageStore.get_github_tree`; `GitHubNode` is the
    public product.
    """

    path_segments: List[str]

    stem: str

    title: str

    @classmethod
    def from_sql_row(
        cls,
        github_owner: str,
        github_repo: str,
        path_prefix: str,
        title: str,
        path_stem: str,
    ) -> GitHubTreeInput:
        path_segments = [github_owner, github_repo]
        if path_prefix:
            path_segments.extend(path_prefix.split("/"))

        return cls(path_segments=path_segments, stem=path_stem, title=title)

    def to_node(self) -> GitHubNode:
        return GitHubNode(
            node_type=GitHubNodeType.page,
            title=self.title,
            path="/".join(self.path_segments + [self.stem]),
            contents=[],
        )
