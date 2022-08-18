"""Domain model for GitHub holdings as a hierarchical tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


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


@dataclass
class GitHubNode:
    """A node in the GitHub contents tree."""

    node_type: GitHubNodeType
    """The type of path object in the node."""

    path_segments: List[str]
    """The segments in the path (i.e. the name of this page, or
    this directory) up to this point.

    Path segments are always ordered:

    1. owner
    2. repo
    3. directory or directories, as necessary
    4. page file stem (i.e. filename without extension)
    """

    title: str
    """Presentational title for this node."""

    github_commit: Optional[str] = None
    """The commit SHA if this tree is for a specific commit (a PR preview)
    instead of corresponding to the default branch of the repository.
    """

    contents: List[GitHubNode] = field(default_factory=list)

    @property
    def squareone_path(self) -> str:
        """Path to the node in Squareone.

        - If `github_commit` is None, the URL path is relative to
          ``/times-square/github/`` (not included.
        - If the node contains a non-None `github_commit`,
          the path is relative to ``/times-square/github-pr/`` (not included).
        """
        if self.github_commit is None:
            # a path corresponding to the default branch (i.e. the "live view
            # github-backed pages)
            return "/".join(self.path_segments)
        else:
            # a path corresponding to the commit view of a repository,
            # for PR previews.
            # formatted as owner/repo/commit/dirname/filestem
            return (
                f"{self.path_segments[0]}/{self.path_segments[1]}/"
                f"{self.github_commit}/{'/'.join(self.path_segments[2:])}"
            )

    @classmethod
    def create_with_repo_root(
        cls, results: List[GitHubTreeQueryResult]
    ) -> GitHubNode:
        """Create a tree with this root-node being the first repository in
        the results.

        This is appropriate for creating trees for GitHub PR previews.
        """
        root_path_segment = [results[0].github_owner, results[0].github_repo]
        root = cls(
            node_type=GitHubNodeType.repo,
            path_segments=root_path_segment,
            github_commit=results[0].github_commit,
            title=results[0].github_repo,
            contents=[],
        )
        for result in results:
            root.insert_node(result)
        return root

    @classmethod
    def create_with_owner_root(
        cls, results: List[GitHubTreeQueryResult]
    ) -> GitHubNode:
        """Create a tree with the root-node being the first GitHub owner in
        the results.

        This is appropriate for creating trees for the default branch views
        of GitHub-backed pages.
        """
        root_path_segment = [results[0].github_owner]
        root = cls(
            node_type=GitHubNodeType.owner,
            path_segments=root_path_segment,
            title=results[0].github_owner,
            github_commit=results[0].github_commit,
            contents=[],
        )
        for result in results:
            root.insert_node(result)
        return root

    def insert_node(self, result: GitHubTreeQueryResult) -> None:
        """Insert an SQL page result as a child (direct, or not) of the
        current node.
        """
        if self.node_type == GitHubNodeType.owner:
            self._insert_node_from_owner(result)
        elif self.node_type == GitHubNodeType.repo:
            self._insert_node_from_repo(result)
        elif self.node_type == GitHubNodeType.directory:
            self._insert_node_from_directory(result)
        else:
            raise ValueError("Cannot insert a node into a page")

    def _insert_node_from_owner(self, result: GitHubTreeQueryResult) -> None:
        # Try to insert node into an existing repository node
        for repo_node in self.contents:
            if repo_node.path_segments[1] == result.github_repo:
                repo_node.insert_node(result)
                return

        # Create a repo node since one doesn't already exist
        repo_node = GitHubNode(
            node_type=GitHubNodeType.repo,
            path_segments=result.path_segments[:2],
            title=result.path_segments[1],
            github_commit=result.github_commit,
            contents=[],
        )
        self.contents.append(repo_node)
        repo_node.insert_node(result)

    def _insert_node_from_repo(self, result: GitHubTreeQueryResult) -> None:
        if len(result.path_segments) == 3:
            # direct child of this node
            self.contents.append(
                GitHubNode(
                    node_type=GitHubNodeType.page,
                    path_segments=result.path_segments,
                    title=result.title,
                    github_commit=result.github_commit,
                    contents=[],
                )
            )
            return
        else:
            # Find existing directory containing this page
            for child_node in self.contents:
                n = len(child_node.path_segments)
                if (
                    child_node.node_type == GitHubNodeType.directory
                    and child_node.path_segments == result.path_segments[:n]
                ):
                    child_node.insert_node(result)
                    return
            # Create a directory node
            dir_node = GitHubNode(
                node_type=GitHubNodeType.directory,
                path_segments=result.path_segments[
                    : len(self.path_segments) + 1
                ],
                title=result.path_segments[len(self.path_segments)],
                github_commit=result.github_commit,
                contents=[],
            )
            self.contents.append(dir_node)
            dir_node.insert_node(result)

    def _insert_node_from_directory(
        self, result: GitHubTreeQueryResult
    ) -> None:
        self_segment_count = len(self.path_segments)
        input_segment_count = len(result.path_segments)

        if input_segment_count == self_segment_count + 1:
            # a direct child of this directory
            self.contents.append(
                GitHubNode(
                    node_type=GitHubNodeType.page,
                    path_segments=result.path_segments,
                    title=result.title,
                    github_commit=result.github_commit,
                    contents=[],
                )
            )
        else:
            # Create a directory node
            dir_node = GitHubNode(
                node_type=GitHubNodeType.directory,
                path_segments=result.path_segments[: self_segment_count + 1],
                title=result.path_segments[self_segment_count],
                github_commit=result.github_commit,
                contents=[],
            )
            self.contents.append(dir_node)
            dir_node.insert_node(result)


@dataclass
class GitHubTreeQueryResult:
    """A domain class used to aid construction of the GitHub contents tree
    from the original SQL storage of pages.
    """

    # The order of these attributes matches the order of the sql query
    # in timessquare.storage.page.

    github_owner: str

    github_repo: str

    github_commit: Optional[str]

    path_prefix: str

    title: str

    path_stem: str

    @property
    def path_segments(self) -> List[str]:
        segments: List[str] = [self.github_owner, self.github_repo]
        if len(self.path_prefix) > 0:
            segments.extend(self.path_prefix.split("/"))
        segments.append(self.path_stem)
        return segments
