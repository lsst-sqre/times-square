"""Domain model for a parameterized notebook page."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping

import jinja2
import jsonschema.exceptions
import nbformat
from jsonschema import Draft202012Validator
from nbconvert.exporters.html import HTMLExporter

from timessquare.exceptions import (
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
    """The name of the page, which is used as a URL path component (slug)."""

    ipynb: str
    """The Jinja-parameterized notebook (a JSON-formatted string)."""

    parameters: Dict[str, PageParameterSchema]
    """The notebook's parameter schemas, keyed by their names."""

    @classmethod
    def create(cls, *, name: str, ipynb: str) -> PageModel:
        """Create a page model given the page's name and source notebook.

        The notebook is parameterized, and the page parameters are defined in
        the Jupyter Notebook's metadata under the ``times-square.parameters``
        path. Each key is a parameter name, and each value is a JSON Schema
        description of that paramter.
        """
        notebook = cls.read_ipynb(ipynb)
        parameters = cls._extract_parameters(notebook)
        return cls(name=name, ipynb=ipynb, parameters=parameters)

    @staticmethod
    def read_ipynb(source: str) -> nbformat.NotebookNode:
        """Parse Jupyter Notebook source into `~NotebookNode` for
        editing of execution.

        The notebook is read according to the `NB_VERSION` notebook version
        constant.
        """
        return nbformat.reads(source, as_version=NB_VERSION)

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
