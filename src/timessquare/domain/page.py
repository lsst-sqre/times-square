"""Domain model for a parameterized notebook page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict

import jsonschema.exceptions
import nbformat
from jsonschema import Draft202012Validator

from timessquare.exceptions import (
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

    parameters: Dict[str, Dict[str, Any]]
    """The notebook's parameters and jsonschema descriptions."""

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

        The notebook is read according the `NB_VERSION` notebook version
        constant.
        """
        return nbformat.reads(source, as_version=NB_VERSION)

    @staticmethod
    def _extract_parameters(
        notebook: nbformat.NotebookNode,
    ) -> Dict[str, Dict[str, Any]]:
        """Get the page parmeters from the notebook.

        Parameters are located in the Jupyter Notebook's metadata under
        the ``times-square.parameters`` path. Each key is a parameter name,
        and each value is a JSON Schema description of that paramter.
        """
        try:
            parameters_metadata = notebook.metadata["times-square"].parameters
        except AttributeError:
            return {}

        for name, schema in parameters_metadata.items():
            PageModel.validate_parameter_schema(name, schema)

        return parameters_metadata

    @staticmethod
    def validate_parameter_schema(name: str, schema: Dict[str, Any]) -> None:
        """Validate a parameter's name and schema.

        Raises
        ------
        ParameterValidationError
            Raised if the parameter is invalid (a specific subclass is raised
            for each type of validation check).
        """
        PageModel.validate_parameter_name(name)

        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ParameterSchemaError(name, str(e))

        validator = Draft202012Validator(schema)

        if "default" not in schema:
            raise ParameterDefaultMissingError(name)
        else:
            if not validator.is_valid(schema["default"]):
                raise ParameterDefaultInvalidError(name, schema["default"])

    @staticmethod
    def validate_parameter_name(name: str) -> None:
        if parameter_name_pattern.match(name) is None:
            raise ParameterNameValidationError(name)
