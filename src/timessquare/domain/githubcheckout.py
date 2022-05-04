"""Domain models for "checkouts" of GitHub repositories containing Times
Square notebooks based on GitHub's Git Tree API for a specific git ref SHA.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, Iterator, List, Optional, Union

import yaml
from gidgethub.httpx import GitHubAPI
from pydantic import BaseModel, EmailStr, Field, HttpUrl, root_validator

from .githubapi import GitHubBlobModel
from .page import PageParameterSchema, PersonModel


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

    blobs_url: str
    """Templated GitHub API URL for the Git blobs API.

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
        return GitHubBlobModel.parse_obj(data)


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

    def to_dict(self) -> Dict[str, Any]:
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
        return str(
            PurePosixPath(self.path_prefix).relative_to(checkout.settings.root)
        )

    def get_display_path(self, checkout: GitHubRepositoryCheckout) -> str:
        """The display path to correlate this GitHub-backed notebook with
        existing pages.

        See also
        --------
        timessquare.domain.page.PageModel.display_path
        """
        display_prefix = self.get_display_path_prefix(checkout)
        name_stem = PurePosixPath(
            PurePosixPath(self.notebook_source_path).name
        ).stem
        return "/".join(
            [checkout.owner_name, checkout.name, display_prefix, name_stem]
        )

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
        title="Paths to ignore (supports globs)",
        default_factory=list,
        description="Relative to the repository root.",
    )

    root: str = Field(
        "",
        title="Root directory where Times Square notebooks are located.",
        description=(
            "An empty string corresponds to the root being the same as "
            "the repository root."
        ),
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

    @classmethod
    def parse_yaml(cls, content: str) -> RepositorySettingsFile:
        """Create a RepositorySettingsFile from the YAML content."""
        return cls.parse_obj(yaml.safe_load(content))


class SidecarPersonModel(BaseModel):
    """A Pydantic model for a person's identity encoded in YAML."""

    name: Optional[str] = Field(title="Display name")

    username: Optional[str] = Field(title="RSP username")

    affiliation_name: Optional[str] = Field(
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

    def to_person_model(self) -> PersonModel:
        """Convert to the domain version of this object."""
        if self.name is not None:
            display_name = self.name
        elif self.username is not None:
            display_name = self.username
        else:
            # Shouldn't be possible thanks to the model validator
            raise RuntimeError("Cannot resolve a display name for person")

        return PersonModel(
            name=display_name,
            username=self.username,
            affiliation_name=self.affiliation_name,
            email=self.email,
            slack_name=self.slack_name,
        )


class JsonSchemaTypeEnum(str, Enum):
    """JSON schema types that are supported."""

    string = "string"
    number = "number"
    integer = "integer"
    boolean = "boolean"


class ParameterSchemaModel(BaseModel):
    """A Pydantic model for a notebook's parameter schema value.

    This model represents how a parameter is formatted in JSON. The
    corresponding domain model that's actually used by the PageModel is
    `PageParameterSchema`.
    """

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

    def to_parameter_schema(self, name: str) -> PageParameterSchema:
        return PageParameterSchema.create_and_validate(
            name=name, json_schema=self.dict()
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

    @classmethod
    def parse_yaml(cls, content: str) -> NotebookSidecarFile:
        """Create a NotebookSidecarFile from the YAML content."""
        return cls.parse_obj(yaml.safe_load(content))

    def export_parameters(self) -> Dict[str, PageParameterSchema]:
        """Export the `parameters` attribute to `PageParameterSchema` used
        by the PageModel.
        """
        return {
            k: v.to_parameter_schema(k) for k, v in self.parameters.items()
        }

    def export_authors(self) -> List[PersonModel]:
        return [a.to_person_model() for a in self.authors]


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
