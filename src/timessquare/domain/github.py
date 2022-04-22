"""Domain models for GitHub repositories containing Times Square notebooks."""

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Union

from gidgethub.httpx import GitHubAPI
from pydantic import BaseModel, EmailStr, Field, HttpUrl, root_validator


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

    git_ref: str
    """The "checked-out" full git ref.

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

    @property
    def full_name(self) -> str:
        """The full repository name (owner/repo format)."""
        return f"{self.owner_name}/{self.name}"

    async def get_git_tree(
        self, github_client: GitHubAPI
    ) -> RecursiveGitTreeModel:
        """Get the recursive git tree of the repository from the GitHub API.

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
        return RecursiveGitTreeModel.parse_obj(response)


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

    @property
    def ipynb(self) -> str:
        """The ipynb file, based on the ``notebook_source`` and including
        Times Square metadata such as parameters.
        """
        # TODO "render" the notebook_source into a Times Square notebook
        # by including parameters data.
        # TODO if we support jupytext, this is where we'd convert that
        # source file into ipynb
        return self.notebook_source


class RepositorySettingsFile(BaseModel):
    """A Pydantic model for a Times Square times-square.yaml repository
    settings file.
    """

    description: Optional[str] = Field(
        None,
        title="Description of the repository",
        description="Can be markdown-formatted.",
    )

    ignore: List[str] = Field(
        title="Paths to ignore (supports globs)", default_factory=list
    )

    enabled: bool = Field(
        True,
        title="Toggle for activating a repository's inclusion in Times Square",
        description=(
            "Normally a repository is synced into Times Square if the Times "
            "Square GitHub App is installed and the repository includes a "
            "times-square.yaml file. You can set this field to `False` to "
            "temporarily prevent it from being synced by Times Square."
        ),
    )


class SidecarPersonModel(BaseModel):
    """A Pydantic model for a person's identity encoded in YAML."""

    name: Optional[str] = Field(title="Display name")

    username: Optional[str] = Field(title="RSP username")

    affilation_name: Optional[str] = Field(
        title="Display name of a person's main affiliation"
    )

    email: Optional[EmailStr] = Field(title="Email")

    slack_name: Optional[str] = Field(title="Slack username")

    @root_validator()
    def check_names(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Either of name or username must be set."""
        keys = values.keys()
        if "name" not in keys and "username" not in keys:
            raise ValueError(
                "Either name or username must be set for a person"
            )
        return values


class JsonSchemaTypeEnum(str, Enum):
    """JSON schema types that are supported."""

    string = "string"
    number = "number"
    integer = "integer"
    boolean = "boolean"


class ParameterSchemaModel(BaseModel):
    """A Pydantic model for a notebook's parameter schema value."""

    type: JsonSchemaTypeEnum = Field(
        title="The JSON schema type.",
        description=(
            "Note that Times Square parameters can only be a subset of types "
            "describable by JSON schema."
        ),
    )

    default: Union[int, float, str, bool] = Field(
        title="Default value, when the user does not override a value"
    )

    description: str = Field(title="Short description of a field")

    minimum: Optional[Union[int, float]] = Field(
        None, title="Minimum value for number or integer types."
    )

    maximum: Optional[Union[int, float]] = Field(
        None, title="Maximum value for number or integer types."
    )

    exclusiveMinimum: Optional[Union[int, float]] = Field(
        None, title="Exclusive minimum value for number or integer types."
    )

    exclusiveMaximum: Optional[Union[int, float]] = Field(
        None, title="Exclusive maximum value for number or integer types."
    )

    multipleOf: Optional[Union[int, float]] = Field(
        None, title="Required factor for number of integer types."
    )


class NotebookSidecarFile(BaseModel):
    """A Pydantic model for a ``{notebook}.yaml`` notebook settings sidecar
    file.
    """

    authors: List[SidecarPersonModel] = Field(
        title="Authors of the notebook", default_factory=list
    )

    title: Optional[str] = Field(
        None,
        title="Title of a notebook (default is to use the filename)",
    )

    description: Optional[str] = Field(
        None,
        title="Description of a notebook",
        description="Can be markdown-formatted.",
    )

    enabled: bool = Field(
        True,
        title="Toggle for activating a notebook's inclusion in Times Square",
    )

    cache_ttl: Optional[int] = Field(
        None, title="Lifetime (seconds) of notebook page renders"
    )

    tags: List[str] = Field(
        title="Tag keywords associated with the notebook", default_factory=list
    )

    parameters: Dict[str, ParameterSchemaModel] = Field(
        title="Parameters and their schemas", default_factory=dict
    )


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

    path: str

    mode: GitTreeMode

    sha: str = Field(title="Git sha of tree object")

    url: HttpUrl = Field(title="URL of the object")

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

    sha: str = Field(title="SHA of the commit.")

    url: HttpUrl = Field(title="GitHub API URL of this resource")

    tree: List[GitTreeItem] = Field(title="Items in the git tree")

    truncated: bool = Field(
        title="True if the dataset does not contain the whole repo"
    )

    def find_notebooks(
        self, settings: RepositorySettingsFile
    ) -> Iterator[RepositoryNotebookTreeRef]:
        """Iterate over all all source notebook+sidecar YAML file pairs in the
        repository, respecting the repository's "ignore" settings.
        """
        # Pre-scan to get an index of all file paths that _could_ be notebook
        # content i.e. ipynb extensions and all YAML paths.
        # TODO if we support jupyext, add more extentions
        # Note: PurePosixPath.suffix includes the period in the extension
        source_extensions = {".ipynb"}
        yaml_extensions = {".yaml", ".yml"}
        notebook_candidate_indices: Dict[str, int] = {}
        yaml_items: List[GitTreeItem] = []
        for i, item in enumerate(self.tree):
            if item.mode == GitTreeMode.file:
                suffix = item.path_extension
                if suffix in source_extensions:
                    notebook_candidate_indices[item.path_stem] = i
                elif suffix in yaml_extensions:
                    yaml_items.append(item)

        for yaml_item in yaml_items:
            path_stem = yaml_item.path_stem
            notebook_item_index = notebook_candidate_indices.get(path_stem)
            if notebook_item_index is None:
                continue
            notebook_item = self.tree[notebook_item_index]

            # Test files again the "ignore" settings
            ignore = False
            for glob_pattern in settings.ignore:
                if yaml_item.match_glob(glob_pattern):
                    ignore = True
                if notebook_item.match_glob(glob_pattern):
                    ignore = True
            if ignore:
                continue

            tree_ref = RepositoryNotebookTreeRef(
                notebook_source_path=notebook_item.path,
                sidecar_path=yaml_item.path,
                notebook_git_tree_sha=notebook_item.sha,
                sidecar_git_tree_sha=yaml_item.sha,
            )
            yield tree_ref


class GitBlobModel(BaseModel):
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
                f"GitHub blbo content encoding {self.encoding} "
                f"is unknown by GitBlobModel for url {self.url}"
            )