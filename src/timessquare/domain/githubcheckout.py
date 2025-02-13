"""Domain models for "checkouts" of GitHub repositories containing Times
Square notebooks based on GitHub's Git Tree API for a specific git ref SHA.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any

from gidgethub.httpx import GitHubAPI
from pydantic import BaseModel, Field, HttpUrl
from safir.github.models import GitHubBlobModel, GitHubRepositoryModel

from timessquare.storage.github.settingsfiles import (
    NotebookSidecarFile,
    RepositorySettingsFile,
)


@dataclass
class GitHubRepositoryCheckout:
    """A domain model GitHub repository, at a specific commit, containing
    Times Square notebooks.

    Notes
    -----
    This domain model is used by the content ingest services to get content
    from the repository at a specific commit, hence the term "checkout"
    in the name. This domain model isn't intended to represent a repository in
    general, or in Times Square's own persistant storage.

    Times Square does not actually check out a git branch or tag, instead it
    uses GitHub's Git Tree API to get the content. See
    `GitHubRepositoryCheckout.get_git_tree`.
    """

    owner_name: str
    """GitHub organization/user that owns the repository."""

    name: str
    """GitHub repository name (without the owner prefix)."""

    settings: RepositorySettingsFile
    """Repository settings, read from times-square.yaml."""

    git_ref: str | None
    """The "checked-out" full git ref, or `None` if a checkout of a bare
    commit.

    Examples:

    - ``refs/heads/main`` (main branch).
    - ``refs/tags/v1.0.0`` (v1.0.0 tag).
    - ``refs/pull/12`` (pull request 12).
    """

    head_sha: str
    """SHA of the "checked-out" git commit."""

    trees_url: str
    """Templated GitHub API URL for the tree API.

    URL variable is ``sha``.
    """

    blobs_url: str
    """Templated GitHub API URL for the Git blobs API.

    URL variable is ``sha``.
    """

    @classmethod
    async def create(
        cls,
        *,
        github_client: GitHubAPI,
        repo: GitHubRepositoryModel,
        head_sha: str,
        git_ref: str | None = None,
    ) -> GitHubRepositoryCheckout:
        uri = repo.contents_url + "{?ref}"
        data = await github_client.getitem(
            uri, url_vars={"path": "times-square.yaml", "ref": head_sha}
        )
        content_data = GitHubBlobModel.model_validate(data)
        file_content = content_data.decode()
        settings = RepositorySettingsFile.parse_yaml(file_content)
        return cls(
            owner_name=repo.owner.login,
            name=repo.name,
            settings=settings,
            git_ref=git_ref,
            head_sha=head_sha,
            trees_url=repo.trees_url,
            blobs_url=repo.blobs_url,
        )

    @property
    def full_name(self) -> str:
        """The full repository name (owner/repo format)."""
        return f"{self.owner_name}/{self.name}"

    async def get_git_tree(
        self, github_client: GitHubAPI
    ) -> RecursiveGitTreeModel:
        """Get the recursive git tree of the repository from the GitHub API
        for this checkout's HEAD SHA (commit).

        Parameters
        ----------
        github_client : `GitHubAPI`
            GitHub client, ideally authorized as a GitHub installation.

        Returns
        -------
        tree : `RecursiveGitTreeModel`
            The contents of the repository's git tree.
        """
        response = await github_client.getitem(
            self.trees_url + "{?recursive}",
            url_vars={"sha": self.head_sha, "recursive": "1"},
        )
        return RecursiveGitTreeModel.model_validate(response)

    async def load_notebook(
        self,
        *,
        notebook_ref: RepositoryNotebookTreeRef,
        github_client: GitHubAPI,
    ) -> RepositoryNotebookModel:
        """Load a notebook from GitHub."""
        # get the sidecar file and parse
        sidecar_blob = await self.load_git_blob(
            github_client=github_client, sha=notebook_ref.sidecar_git_tree_sha
        )
        sidecar_file = NotebookSidecarFile.parse_yaml(sidecar_blob.decode())

        # Get the source content
        source_blob = await self.load_git_blob(
            github_client=github_client, sha=notebook_ref.notebook_git_tree_sha
        )

        return RepositoryNotebookModel(
            notebook_source_path=notebook_ref.notebook_source_path,
            sidecar_path=notebook_ref.sidecar_path,
            notebook_git_tree_sha=notebook_ref.notebook_git_tree_sha,
            sidecar_git_tree_sha=notebook_ref.sidecar_git_tree_sha,
            notebook_source=source_blob.decode(),
            sidecar=sidecar_file,
        )

    async def load_git_blob(
        self, *, github_client: GitHubAPI, sha: str
    ) -> GitHubBlobModel:
        data = await github_client.getitem(
            self.blobs_url, url_vars={"sha": sha}
        )
        return GitHubBlobModel.model_validate(data)


@dataclass(kw_only=True)
class RepositoryNotebookTreeRef:
    """A domain model for a notebook in a GitHub repository that uses only
    the deta available from the Git tree, without content.

    Use RepositoryNotebookModel to include content.
    """

    notebook_source_path: str
    """Repository file path to the notebook source file (typically with an
    ``ipynb`` extension).
    """

    sidecar_path: str
    """Repository file path to the side sidecar configuration file (typically
    with a ``yaml`` extension).
    """

    notebook_git_tree_sha: str
    """Git sha of the notebook file."""

    sidecar_git_tree_sha: str
    """Git sha of the sidecar file."""

    def to_dict(self) -> dict[str, Any]:
        """Export as a dictionary."""
        return asdict(self)


@dataclass(kw_only=True)
class RepositoryNotebookModel(RepositoryNotebookTreeRef):
    """A domain model for a notebook in a GitHub repository."""

    notebook_source: str
    """Source content of the notebook file."""

    sidecar: NotebookSidecarFile
    """Contents of the notebook's sidecar configuration file."""

    @property
    def title(self) -> str:
        """Title of the notebook page.

        If available, this is the "title" field set in the sidecar file.
        Otherwise it is the filename of the notebook source file (without
        its extension).
        """
        if self.sidecar.title:
            return self.sidecar.title
        else:
            path = PurePosixPath(self.notebook_source_path)
            return PurePosixPath(path.name).stem

    @property
    def path_prefix(self) -> str:
        """Directories this notebook is contained in, or "" for the root
        directory.
        """
        dirname = str(PurePosixPath(self.notebook_source_path).parent)
        if dirname == ".":
            return ""
        else:
            return dirname

    def get_display_path_prefix(
        self, checkout: GitHubRepositoryCheckout
    ) -> str:
        prefix = str(
            PurePosixPath(self.path_prefix).relative_to(checkout.settings.root)
        )
        if prefix == ".":
            return ""
        else:
            return prefix

    def get_display_path(self, checkout: GitHubRepositoryCheckout) -> str:
        """Get the display path to correlate this GitHub-backed notebook with
        existing pages.

        See Also
        --------
        timessquare.domain.page.PageModel.display_path
        """
        display_prefix = self.get_display_path_prefix(checkout)
        name_stem = PurePosixPath(
            PurePosixPath(self.notebook_source_path).name
        ).stem
        if display_prefix:
            return (
                f"{checkout.owner_name}/{checkout.name}/"
                f"{display_prefix}/{name_stem}"
            )
        else:
            return f"{checkout.owner_name}/{checkout.name}/{name_stem}"

    @property
    def ipynb(self) -> str:
        """The ipynb file, based on the ``notebook_source`` and including
        Times Square metadata such as parameters.
        """
        # If we support jupytext, this is where we'd convert that
        # source file into ipynb
        return self.notebook_source


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

    def find_notebooks(
        self, settings: RepositorySettingsFile
    ) -> Iterator[RepositoryNotebookTreeRef]:
        """Iterate over all all source notebook+sidecar YAML file pairs in the
        repository, respecting the repository's "ignore" settings.
        """
        # Pre-scan to get an index of all file paths that _could_ be notebook
        # content i.e. ipynb extensions and all YAML paths.
        # If we support jupyext, add more extentions
        # Note: PurePosixPath.suffix includes the period in the extension
        source_extensions = {".ipynb"}
        yaml_extensions = {".yaml", ".yml"}
        notebook_candidate_indices: dict[str, int] = {}
        yaml_items: list[GitTreeItem] = []
        for i, item in enumerate(self.tree):
            if item.mode == GitTreeMode.file:
                suffix = item.path_extension
                if suffix in source_extensions:
                    notebook_candidate_indices[item.path_stem] = i
                elif suffix in yaml_extensions:
                    yaml_items.append(item)

        for yaml_item in yaml_items:
            # Test files against the "ignore" settings
            if self._is_ignored(yaml_item, settings):
                continue

            path_stem = yaml_item.path_stem
            notebook_item_index = notebook_candidate_indices.get(path_stem)
            if notebook_item_index is None:
                continue
            notebook_item = self.tree[notebook_item_index]

            tree_ref = RepositoryNotebookTreeRef(
                notebook_source_path=notebook_item.path,
                sidecar_path=yaml_item.path,
                notebook_git_tree_sha=notebook_item.sha,
                sidecar_git_tree_sha=yaml_item.sha,
            )
            yield tree_ref

    def _is_ignored(
        self, yaml_item: GitTreeItem, settings: RepositorySettingsFile
    ) -> bool:
        """Test if a file is ignored by the repository settings."""
        for glob_pattern in settings.ignore:
            if yaml_item.match_glob(glob_pattern):
                return True
        return False
