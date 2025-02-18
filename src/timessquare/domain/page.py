"""Domain model for a parameterized notebook page."""

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Self
from uuid import uuid4

import jinja2
import nbformat

from timessquare.exceptions import PageJinjaError, PageNotebookFormatError

from ..config import config
from ..storage.noteburst import NoteburstJobModel
from .pageparameters import PageParameters

NB_VERSION = 4
"""The notebook format version used for reading and writing notebooks.

Generally this version should be upgraded as needed to support more modern
notebook formats, while also being compatible with this app.
"""


@dataclass
class PageModel:
    """The domain model for a page, which is a parameterized notebook that
    is available as a web page.
    """

    name: str
    """The name of the page, which is used as an API URL path component
    (slug).
    """

    ipynb: str
    """The Jinja-parameterized notebook (a JSON-formatted string)."""

    parameters: PageParameters
    """The notebook's parameter schemas, keyed by their names."""

    title: str
    """The presentation title of the page."""

    date_added: datetime
    """Date when the page is registered through the Times Square API."""

    authors: list[PersonModel] = field(default_factory=list)
    """Authors of the notebook."""

    tags: list[str] = field(default_factory=list)
    """Tags (keywords) assigned to this page."""

    uploader_username: str | None = None
    """Username of the uploader, if this page is uploaded without GitHub
    backing.
    """

    date_deleted: datetime | None = None
    """A nullable datetime that is set to the datetime when the page is
    soft-deleted.
    """

    description: str | None = None
    """Description of a page (markdown-formatted)."""

    cache_ttl: int | None = None
    """The cache TTL (seconds) for HTML renders, or None to retain renders
    indefinitely.
    """

    github_owner: str | None = None
    """The GitHub repository owner (username or organization name) for
    GitHub-backed pages.
    """

    github_repo: str | None = None
    """The GitHub repository name for GitHub-backed pages."""

    github_commit: str | None = None
    """The SHA of the commit this page corresponds to; only used for pages
    associated with a GitHub Check Run.
    """

    repository_path_prefix: str | None = None
    """The repository path prefix, relative to the root of the repository."""

    repository_display_path_prefix: str | None = None
    """The repository path prefix, relative to the configured root of Times
    Square notebooks in a repository.
    """

    repository_path_stem: str | None = None
    """The file name stem (without directory prefix and without extensions)
    for both the source and sidecar file

    Use `repository_source_extension` or `repository_sidecar_extension` to
    get the corresponding file name (or see the dynamic properties
    `repository_source_filename` or `repository_sidecar_filename`
    """

    repository_source_extension: str | None = None
    """The filename extension of the source file in the GitHub repository for
    GitHub-backed pages.
    """

    repository_sidecar_extension: str | None = None
    """The filename extension of the sidecar YAML file in the GitHub repository
    for GitHub-backed pages.
    """

    repository_source_sha: str | None = None
    """The git tree sha of the source file for GitHub-backed pages."""

    repository_sidecar_sha: str | None = None
    """The git tree sha of the sidecar YAML file for GitHub-backed pages."""

    @classmethod
    def create_from_api_upload(
        cls,
        *,
        ipynb: str,
        title: str,
        uploader_username: str,
        description: str | None = None,
        cache_ttl: int | None = None,
        tags: list[str] | None = None,
        authors: list[PersonModel] | None = None,
    ) -> PageModel:
        """Create a page model given an API upload of a notebook.

        The notebook is parameterized, and the page parameters are defined in
        the Jupyter Notebook's metadata under the ``times-square.parameters``
        path. Each key is a parameter name, and each value is a JSON Schema
        description of that paramter.
        """
        notebook = cls.read_ipynb(ipynb)
        parameters = PageParameters.create_from_notebook(notebook)

        name = uuid4().hex  # random slug for API uploads
        date_added = datetime.now(UTC)

        if not authors:
            # Create a default author using the uploader info
            authors = [
                PersonModel(name=uploader_username, username=uploader_username)
            ]

        return cls(
            name=name,
            ipynb=ipynb,
            parameters=parameters,
            title=title,
            tags=tags if tags else [],
            authors=authors,
            date_added=date_added,
            description=description,
            cache_ttl=cache_ttl,
        )

    @classmethod
    def create_from_repo(
        cls,
        *,
        ipynb: str,
        title: str,
        parameters: PageParameters,
        github_owner: str,
        github_repo: str,
        repository_path_prefix: str,
        repository_display_path_prefix: str,
        repository_path_stem: str,
        repository_source_extension: str,
        repository_sidecar_extension: str,
        repository_source_sha: str,
        repository_sidecar_sha: str,
        description: str | None = None,
        cache_ttl: int | None = None,
        tags: list[str] | None = None,
        authors: list[PersonModel] | None = None,
        github_commit: str | None = None,
    ) -> PageModel:
        name = uuid4().hex  # random slug for API uploads
        date_added = datetime.now(UTC)

        return cls(
            name=name,
            ipynb=ipynb,
            parameters=parameters,
            title=title,
            tags=tags if tags else [],
            authors=authors if authors else [],
            date_added=date_added,
            description=description,
            cache_ttl=cache_ttl,
            github_owner=github_owner,
            github_repo=github_repo,
            github_commit=github_commit,
            repository_path_prefix=repository_path_prefix,
            repository_display_path_prefix=repository_display_path_prefix,
            repository_path_stem=repository_path_stem,
            repository_source_extension=repository_source_extension,
            repository_sidecar_extension=repository_sidecar_extension,
            repository_source_sha=repository_source_sha,
            repository_sidecar_sha=repository_sidecar_sha,
        )

    @property
    def github_backed(self) -> bool:
        """A flag identifying that the page is GitHub backed.

        For API-sourced pages, this attribute is `False`.
        """
        return bool(
            self.repository_display_path_prefix is not None
            and self.repository_path_stem is not None
            and self.repository_source_extension is not None
            and self.repository_sidecar_extension is not None
            and self.repository_source_sha is not None
            and self.repository_sidecar_sha is not None
            and self.repository_display_path_prefix is not None
            and self.github_owner is not None
            and self.github_repo is not None
        )

    @property
    def display_path(self) -> str:
        """The page's display path for universal identification.

        Notes
        -----
        The "display path" is a string that helps to universally identify a
        notebook. It's most relevant for GitHub-backed pages, to identify that
        a page is equivalent to a source found in a GitHub repository.

        For GitHub-backed pages, the display path is a POSIX path based on:

        - repo owner
        - repo name
        - `repository_display_path_prefix`
        - `repository_path_stem.

        For API-sourced pages, the display path is the `name` (UUID4
        identifier).
        """
        if self.github_backed:
            if self.repository_display_path_prefix is None:
                raise RuntimeError("repository_display_path_prefix is None")
            if self.repository_path_stem is None:
                raise RuntimeError("repository_path_stem is None")
            path = str(
                PurePosixPath(self.repository_display_path_prefix).joinpath(
                    self.repository_path_stem
                )
            )
            return f"{self.github_owner}/{self.github_repo}/{path}"
        else:
            return self.name

    @property
    def repository_source_filename(self) -> str | None:
        """The filename (without prefix) of the source file in the GitHub
        repository for GitHub-backed pages.
        """
        if self.repository_path_stem and self.repository_source_extension:
            return self.repository_path_stem + self.repository_source_extension
        else:
            return None

    @property
    def repository_sidecar_filename(self) -> str | None:
        """The filename (without prefix) of the sidecar YAML file in the GitHub
        repository for GitHub-backed pages.
        """
        if self.repository_path_stem and self.repository_sidecar_extension:
            return (
                self.repository_path_stem + self.repository_sidecar_extension
            )
        else:
            return None

    @property
    def repository_source_path(self) -> str | None:
        source_filename = self.repository_source_filename
        if source_filename is None:
            return None
        if self.repository_path_prefix is None:
            return None

        return str(
            PurePosixPath(self.repository_path_prefix).joinpath(
                source_filename
            )
        )

    @property
    def repository_sidecar_path(self) -> str | None:
        sidecar_filename = self.repository_sidecar_filename
        if sidecar_filename is None:
            return None
        if self.repository_path_prefix is None:
            return None

        return str(
            PurePosixPath(self.repository_path_prefix).joinpath(
                sidecar_filename
            )
        )

    @property
    def execution_timeout(self) -> timedelta:
        """The execution timeout for the page, in seconds.

        Note
        ----
        Currently this timeout defaults to the `default_execution_timeout`
        configuration value. In the future, this setting may be configurable
        per-page. At that time, this property will use the per-page setting,
        falling back to the Times Square default if not set.
        """
        return timedelta(seconds=config.default_execution_timeout)

    @staticmethod
    def read_ipynb(source: str) -> nbformat.NotebookNode:
        """Parse Jupyter Notebook source into `~NotebookNode` for
        editing of execution.

        The notebook is read according to the `NB_VERSION` notebook version
        constant.
        """
        try:
            return nbformat.reads(source, as_version=NB_VERSION)
        except Exception as e:
            message = f"The notebook is not a valid ipynb file.\n\n{e}"
            raise PageNotebookFormatError(message) from e

    @staticmethod
    def write_ipynb(notebook: nbformat.NotebookNode) -> str:
        """Write a notebook back into a JSON-encoded string.

        The notebook is written according to the `NB_VERSION` notebook version
        constant.
        """
        return nbformat.writes(notebook, version=NB_VERSION)


@dataclass
class PersonModel:
    """A domain model for rich information about a person, such as an author
    of a notebook.
    """

    name: str
    """A person's display name."""

    username: str | None = None
    """A person's RSP username."""

    affiliation_name: str | None = None
    """Display name of a person's main affiliation."""

    email: str | None = None
    """A person's email."""

    slack_name: str | None = None
    """A person's Slack handle."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PersonModel:
        return cls(
            name=d["name"],
            username=d.get("username"),
            affiliation_name=d.get("affiliation_name"),
            email=d.get("email"),
            slack_name=d.get("slack_name"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageSummaryModel:
    """The domain model for a page summary, which is a subset of information
    about a page that's useful for constructing index UIs.
    """

    name: str
    """The name of the page, which is used as a URL path component (slug)."""

    title: str
    """The display title of the page."""


@dataclass
class PageIdModel:
    """A domain model that identifies a page and creates a reproducible key
    string for a page.
    """

    name: str
    """The name of the page, which is used as a URL path component (slug)."""

    @property
    def cache_key_prefix(self) -> str:
        return f"{self.name}/"


@dataclass
class PageInstanceIdModel(PageIdModel):
    """The domain model that identifies an instance of a page through the
    page's name and values of parameters.

    The `cache_key` property produces a reproducible key string, useful as
    a Redis key.
    """

    values: dict[str, Any]
    """The values of a page instance's parameters.

    Keys are parameter names, and values are the parameter values.
    The values are cast as Python types (`PageParameterSchema.cast_value`).
    """

    @property
    def cache_key(self) -> str:
        encoded_values_key = b64encode(
            json.dumps(dict(self.values.items()), sort_keys=True).encode(
                "utf-8"
            )
        ).decode("utf-8")
        return f"{super().cache_key_prefix}{encoded_values_key}"


@dataclass
class PageInstanceModel(PageInstanceIdModel):
    """A domain model for a page instance, which combines the page model with
    information identifying the values a specific page instance is rendered
    with.
    """

    page: PageModel
    """The page domain object."""

    @classmethod
    def create(cls, page: PageModel, values: Mapping[str, Any]) -> Self:
        """Create a page instance given a page and parameter values.

        The parameter values are treated as user-inputs (like from the web API
        query string) and are resolved and validated by this constructor.
        """
        resolved_values = page.parameters.resolve_values(values)
        return cls(name=page.name, page=page, values=resolved_values)

    def render_ipynb(self) -> str:
        """Render the ipynb notebook.

        This method replaces the first code cell with parameter assignments,
        renders Jinja templating in all Markdown cells, and updates the
        notebook's metadata with the parameter values.

        Returns
        -------
        str
            JSON-encoded notebook source.

        Raises
        ------
        PageJinjaError
            Raised if there is an error rendering the Jinja template.
        """
        # Build Jinja render context with parameter values
        # Turn off autoescaping to avoid escaping the parameter values
        jinja_env = jinja2.Environment(autoescape=False)  # noqa: S701
        jinja_env.globals.update({"params": self.values})

        # Read notebook and render cell-by-cell
        notebook = self.page.read_ipynb(self.page.ipynb)
        processed_first_cell = False
        for cell_index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                if processed_first_cell is False:
                    # Handle first code cell specially by replacing it with a
                    # cell that sets Python variables to their values
                    cell.source = self._create_parameter_assignment_cell()
                    processed_first_cell = True
                else:
                    # Only process the first code cell
                    continue

            # Render the templated cell
            try:
                template = jinja_env.from_string(cell.source)
                cell.source = template.render()
            except Exception as e:
                raise PageJinjaError(str(e), cell_index) from e

        # Modify notebook metadata to include values
        if "times-square" not in notebook.metadata:
            notebook.metadata["times-square"] = {}
        notebook.metadata["times-square"]["values"] = {
            name: self.page.parameters[name].create_json_value(value)
            for name, value in self.values.items()
        }
        # Render notebook back to a string and return
        return PageModel.write_ipynb(notebook)

    def _create_parameter_assignment_cell(self) -> str:
        """Create the Python code cell in the notebook instance that assigns
        parameter values to variables.

        Returns
        -------
        str
            The Python code cell as a string.
        """
        sorted_variables = sorted(self.values.keys())
        code_lines = [
            self.page.parameters[name].create_python_assignment(
                name, self.values[name]
            )
            for name in sorted_variables
        ]
        code_lines.insert(0, "# Parameters")
        return "\n".join(code_lines)


@dataclass(kw_only=True)
class PageExecutionInfo(PageInstanceModel):
    """A domain model for information about a new page, including information
    about the noteburst job that processes the page's default instantiation.
    """

    noteburst_status_code: int

    noteburst_error_message: str | None = None

    noteburst_job: NoteburstJobModel | None = None
    """The noteburst job that is processing the new page's default form."""
