"""Domain model for a parameterized notebook page."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional
from uuid import uuid4

import jinja2
import jsonschema.exceptions
import nbformat
from jsonschema import Draft202012Validator
from nbconvert.exporters.html import HTMLExporter

from timessquare.exceptions import (
    PageNotebookFormatError,
    PageParameterError,
    PageParameterValueCastingError,
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
    ParameterSchemaError,
)

NB_VERSION = 4
"""The notebook format version used for reading and writing notebooks.

Generally this version should be upgraded as needed to support more modern
notebook formats, while also being compatible with this app.
"""

parameter_name_pattern = re.compile(
    r"^"
    r"[a-zA-Z]"  # initial characters are letters only
    r"[_a-zA-Z0-9]*$"  # following characters are letters and numbers
    r"$"
)
"""Regular expression that matches a valid parameter name."""


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

    parameters: Dict[str, PageParameterSchema]
    """The notebook's parameter schemas, keyed by their names."""

    title: str
    """The presentation title of the page."""

    date_added: datetime
    """Date when the page is registered through the Times Square API."""

    authors: List[PersonModel] = field(default_factory=list)
    """Authors of the notebook."""

    tags: List[str] = field(default_factory=list)
    """Tags (keywords) assigned to this page."""

    uploader_username: Optional[str] = None
    """Username of the uploader, if this page is uploaded without GitHub
    backing.
    """

    date_deleted: Optional[datetime] = None
    """A nullable datetime that is set to the datetime when the page is
    soft-deleted.
    """

    description: Optional[str] = None
    """Description of a page (markdown-formatted)."""

    cache_ttl: Optional[int] = None
    """The cache TTL (seconds) for HTML renders, or None to retain renders
    indefinitely.
    """

    github_owner: Optional[str] = None
    """The GitHub repository owner (username or organization name) for
    GitHub-backed pages.
    """

    github_repo: Optional[str] = None
    """The GitHub repository name for GitHub-backed pages."""

    repository_path_prefix: Optional[str] = None
    """The repository path prefix, relative to the root of the repository."""

    repository_display_path_prefix: Optional[str] = None
    """The repository path prefix, relative to the configured root of Times
    Square notebooks in a repository.
    """

    repository_path_stem: Optional[str] = None
    """The file name stem (without directory prefix and without extensions)
    for both the source and sidecar file

    Use `repository_source_extension` or `repository_sidecar_extension` to
    get the corresponding file name (or see the dynamic properties
    `repository_source_filename` or `repository_sidecar_filename`
    """

    repository_source_extension: Optional[str] = None
    """The filename extension of the source file in the GitHub repository for
    GitHub-backed pages.
    """

    repository_sidecar_extension: Optional[str] = None
    """The filename extension of the sidecar YAML file in the GitHub repository
    for GitHub-backed pages.
    """

    repository_source_sha: Optional[str] = None
    """The git tree sha of the source file for GitHub-backed pages."""

    repository_sidecar_sha: Optional[str] = None
    """The git tree sha of the sidecar YAML file for GitHub-backed pages."""

    @classmethod
    def create_from_api_upload(
        cls,
        *,
        ipynb: str,
        title: str,
        uploader_username: str,
        description: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
        authors: Optional[List[PersonModel]] = None,
    ) -> PageModel:
        """Create a page model given an API upload of a notebook.

        The notebook is parameterized, and the page parameters are defined in
        the Jupyter Notebook's metadata under the ``times-square.parameters``
        path. Each key is a parameter name, and each value is a JSON Schema
        description of that paramter.
        """
        notebook = cls.read_ipynb(ipynb)
        parameters = cls._extract_parameters(notebook)

        name = uuid4().hex  # random slug for API uploads
        date_added = datetime.now(timezone.utc)

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
            tags=tags if tags else list(),
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
        parameters: Dict[str, PageParameterSchema],
        github_owner: str,
        github_repo: str,
        repository_path_prefix: str,
        repository_display_path_prefix: str,
        repository_path_stem: str,
        repository_source_extension: str,
        repository_sidecar_extension: str,
        repository_source_sha: str,
        repository_sidecar_sha: str,
        description: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        tags: Optional[List[str]] = None,
        authors: Optional[List[PersonModel]] = None,
    ) -> PageModel:
        name = uuid4().hex  # random slug for API uploads
        date_added = datetime.now(timezone.utc)

        return cls(
            name=name,
            ipynb=ipynb,
            parameters=parameters,
            title=title,
            tags=tags if tags else list(),
            authors=authors if authors else list(),
            date_added=date_added,
            description=description,
            cache_ttl=cache_ttl,
            github_owner=github_owner,
            github_repo=github_repo,
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
        if (
            self.repository_display_path_prefix is not None
            and self.repository_path_stem is not None
            and self.repository_source_extension is not None
            and self.repository_sidecar_extension is not None
            and self.repository_source_sha is not None
            and self.repository_sidecar_sha is not None
            and self.repository_display_path_prefix is not None
            and self.github_owner is not None
            and self.github_repo is not None
        ):
            return True
        else:
            return False

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
            assert self.repository_display_path_prefix is not None
            assert self.repository_path_stem is not None
            path = str(
                PurePosixPath(self.repository_display_path_prefix).joinpath(
                    self.repository_path_stem
                )
            )
            return f"{self.github_owner}/{self.github_repo}/{path}"
        else:
            return self.name

    @property
    def repository_source_filename(self) -> Optional[str]:
        """The filename (without prefix) of the source file in the GitHub
        repository for GitHub-backed pages.
        """
        if self.repository_path_stem and self.repository_source_extension:
            return self.repository_path_stem + self.repository_source_extension
        else:
            return None

    @property
    def repository_sidecar_filename(self) -> Optional[str]:
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
    def repository_source_path(self) -> Optional[str]:
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
    def repository_sidecar_path(self) -> Optional[str]:
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
            raise PageNotebookFormatError(str(e))

    @staticmethod
    def write_ipynb(notebook: nbformat.NotebookNode) -> str:
        """Write a notebook back into a JSON-encoded string.

        The notebook is written according to the `NB_VERSION` notebook version
        constant.
        """
        return nbformat.writes(notebook, version=NB_VERSION)

    @staticmethod
    def _extract_parameters(
        notebook: nbformat.NotebookNode,
    ) -> Dict[str, PageParameterSchema]:
        """Get the page parmeters from the notebook.

        Parameters are located in the Jupyter Notebook's metadata under
        the ``times-square.parameters`` path. Each key is a parameter name,
        and each value is a JSON Schema description of that paramter.
        """
        try:
            parameters_metadata = notebook.metadata["times-square"].parameters
        except AttributeError:
            return {}

        page_parameters = {
            name: PageModel.create_and_validate_page_parameter(name, schema)
            for name, schema in parameters_metadata.items()
        }

        return page_parameters

    @staticmethod
    def create_and_validate_page_parameter(
        name: str, schema: Dict[str, Any]
    ) -> PageParameterSchema:
        """Validate a parameter's name and schema.

        Raises
        ------
        ParameterValidationError
            Raised if the parameter is invalid (a specific subclass is raised
            for each type of validation check).
        """
        PageModel.validate_parameter_name(name)
        return PageParameterSchema.create_and_validate(
            name=name, json_schema=schema
        )

    @staticmethod
    def validate_parameter_name(name: str) -> None:
        if parameter_name_pattern.match(name) is None:
            raise ParameterNameValidationError(name)

    def resolve_and_validate_parameters(
        self, requested_parameters: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Resolve and validate parameter values for a notebook based on
        a possibly incomplete user request.

        Parameters
        ----------
        requested_parameters : dict
            User-specified values for parameters. If parameters are not set by
            the user, the parameter's defaults are used intead.
        """
        # Collect the values for each parameter; either from the request or
        # the default. Avoid extraneous parameters from the request for
        # security.
        resolved_values = {
            name: requested_parameters.get(name, schema.default)
            for name, schema in self.parameters.items()
        }

        # Cast to the correct types
        cast_values: Dict[str, Any] = {}
        for name, value in resolved_values.items():
            try:
                cast_values[name] = self.parameters[name].cast_value(value)
            except PageParameterValueCastingError:
                raise PageParameterError(name, value, self.parameters[name])

        # Ensure each parameter's value is valid
        for name, value in cast_values.items():
            if not self.parameters[name].validate(value):
                raise PageParameterError(name, value, self.parameters[name])

        return cast_values

    def render_parameters(
        self,
        values: Mapping[str, Any],
    ) -> str:
        """Render the Jinja template in the source notebook cells with
        specified parameter values.

        **Note**: parameter values are not validated. Use
        resolve_and_validate_parameters first.

        Parameters
        ----------
        requested_parameters : `dict`
            Parameter values.

        Returns
        -------
        ipynb : str
            JSON-encoded notebook source.
        """
        # Build Jinja render context
        jinja_env = jinja2.Environment()
        jinja_env.globals.update({"params": values})

        # Read notebook and render cell-by-cell
        notebook = PageModel.read_ipynb(self.ipynb)
        for cell in notebook.cells:
            template = jinja_env.from_string(cell.source)
            cell.source = template.render()

        # Modify notebook metadata to include values
        if "times-square" not in notebook.metadata.keys():
            notebook.metadata["times-square"] = {}
        notebook.metadata["times-square"]["values"] = values

        # Render notebook back to a string and return
        return PageModel.write_ipynb(notebook)

    def render_html(self, ipynb: str) -> str:
        """Render a notebook into HTML."""
        notebook = PageModel.read_ipynb(ipynb)
        exporter = HTMLExporter()
        html, resources = exporter.from_notebook_node(notebook)
        return html


@dataclass
class PersonModel:
    """A domain model for rich information about a person, such as an author
    of a notebook.
    """

    name: str
    """A person's display name."""

    username: Optional[str] = None
    """A person's RSP username."""

    affiliation_name: Optional[str] = None
    """Display name of a person's main affiliation."""

    email: Optional[str] = None
    """A person's email."""

    slack_name: Optional[str] = None
    """A person's Slack handle."""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PersonModel:
        return cls(
            name=d["name"],
            username=d.get("username"),
            affiliation_name=d.get("affiliation_name"),
            email=d.get("email"),
            slack_name=d.get("slack_name"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageParameterSchema:
    """The domain model for a page parameter's JSON schema, which is a template
    variable in a page's notebook (`PageModel`).
    """

    validator: Draft202012Validator
    """Parameter value validator (based on `json_schema`)."""

    @classmethod
    def create(cls, json_schema: Dict[str, Any]) -> PageParameterSchema:
        """Create a PageParameterSchema given a JSON Schema.

        Note that this method does not validate the schema. If the schema is
        being instantiated from an external source, run the
        `create_and_validate` constructor instead.
        """
        return cls(validator=Draft202012Validator(json_schema))

    @classmethod
    def create_and_validate(
        cls, name: str, json_schema: Dict[str, Any]
    ) -> PageParameterSchema:
        try:
            Draft202012Validator.check_schema(json_schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ParameterSchemaError(name, str(e))

        if "default" not in json_schema:
            raise ParameterDefaultMissingError(name)

        instance = cls.create(json_schema)
        if not instance.validate(json_schema["default"]):
            raise ParameterDefaultInvalidError(name, json_schema["default"])

        return instance

    @property
    def schema(self) -> Dict[str, Any]:
        """Get the JSON schema."""
        return self.validator.schema

    @property
    def default(self) -> Any:
        """Get the schema's default value."""
        return self.schema["default"]

    def __str__(self) -> str:
        return json.dumps(self.schema, sort_keys=True, indent=2)

    def validate(self, v: Any) -> bool:
        """Validate a parameter value."""
        return self.validator.is_valid(v)

    def cast_value(self, v: Any) -> Any:
        """Cast a value to the type indicated by the schema.

        Often the input value is a string value usually obtained from the URL
        query parameters into the correct type based on the JSON Schema's type.
        You can also safely pass the correct type idempotently.

        Only string, integer, number, and boolean schema types are supported.
        """
        schema_type = self.schema.get("type")
        if schema_type is None:
            return v

        try:
            if schema_type == "string":
                return v
            elif schema_type == "integer":
                return int(v)
            elif schema_type == "number":
                if isinstance(v, str):
                    if "." in v:
                        return float(v)
                    else:
                        return int(v)
                else:
                    return v
            elif schema_type == "boolean":
                if isinstance(v, str):
                    if v.lower() == "true":
                        return True
                    elif v.lower() == "false":
                        return False
                    else:
                        raise ValueError
                else:
                    return v
            else:
                raise ValueError
        except ValueError:
            raise PageParameterValueCastingError(v, schema_type)


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
class PageInstanceIdModel:
    """The domain model that identifies an instance of a page through the
    page's name and values of parameters.
    """

    name: str
    """The name of the page, which is used as a URL path component (slug)."""

    values: Dict[str, Any]
    """The values of a page instance's parameters.

    Keys are parameter names, and values are the parameter values.
    The values are cast as Python types (`PageParameterSchema.cast_value`).
    """


@dataclass
class PageInstanceModel(PageInstanceIdModel):
    """A domain model for a page instance, which combines the page model with
    information identifying the values a specific page instance is rendered
    with.
    """

    page: PageModel
    """The page domain object."""
