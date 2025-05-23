"""Domain of page parameters."""

from __future__ import annotations

import keyword
from collections.abc import Iterator, Mapping
from typing import Any, Self

import jsonschema.exceptions
import nbformat
from jsonschema import Draft202012Validator

from timessquare.exceptions import (
    PageParameterError,
    PageParameterValueCastingError,
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
    ParameterSchemaError,
)

from ._booleanparameter import BooleanParameterSchema
from ._dateparameter import DateParameterSchema
from ._datetimeparameter import DatetimeParameterSchema
from ._integerparameter import IntegerParameterSchema
from ._numberparameter import NumberParameterSchema
from ._schemabase import PageParameterSchema
from ._stringparameter import StringParameterSchema

__all__ = [
    "PageParameters",
    "create_and_validate_parameter_schema",
    "create_page_parameter_schema",
]


def create_page_parameter_schema(
    json_schema: dict[str, Any],
) -> PageParameterSchema:
    """Create a PageParameterSchema given a JSON Schema.

    Note that this method does not validate the schema. If the schema is
    being instantiated from an external source, run the
    `create_and_validate` constructor instead.
    """
    validator = Draft202012Validator(json_schema)
    schema_type = validator.schema.get("type", "string")
    schema_format = validator.schema.get("format", None)
    if schema_type == "string" and schema_format is None:
        return StringParameterSchema(validator=validator)
    elif schema_type == "integer":
        return IntegerParameterSchema(validator=validator)
    elif schema_type == "number":
        return NumberParameterSchema(validator=validator)
    elif schema_type == "boolean":
        return BooleanParameterSchema(validator=validator)
    elif schema_type == "string" and schema_format == "date":
        return DateParameterSchema(validator=validator)
    elif schema_type == "string" and schema_format == "date-time":
        return DatetimeParameterSchema(validator=validator)

    raise ValueError(f"Unsupported schema type: {schema_type}")


def create_and_validate_parameter_schema(
    name: str, json_schema: dict[str, Any]
) -> PageParameterSchema:
    try:
        Draft202012Validator.check_schema(json_schema)
    except jsonschema.exceptions.SchemaError as e:
        message = f"The schema for the {name} parameter is invalid.\n\n{e}"
        raise ParameterSchemaError.for_param(name, message) from e

    if "default" not in json_schema and "X-Dynamic-Default" not in json_schema:
        raise ParameterDefaultMissingError.for_param(name)

    instance = create_page_parameter_schema(json_schema)
    # Refactor validation of default into the PageParmaterSchema
    if "default" in json_schema and not instance.validate(
        json_schema["default"]
    ):
        raise ParameterDefaultInvalidError.for_param(
            name, json_schema["default"]
        )

    return instance


class PageParameters(Mapping):
    """Parameterizations for a page.

    Parameters
    ----------
    parameter_schemas
        A dictionary of parameter names to their schemas
    """

    def __init__(
        self, parameter_schemas: dict[str, PageParameterSchema]
    ) -> None:
        self._parameter_schemas = parameter_schemas
        # Validate parameter names
        for name in self._parameter_schemas:
            self.validate_parameter_name(name)

    @classmethod
    def create_from_notebook(cls, nb: nbformat.NotebookNode) -> Self:
        """Create a `PageParameters` instance from a Jupyter notebook.

        Parameters are extracted from the notebook's metadata. If the notebook
        does not have any parameters, an empty `PageParameters` instance is
        returned.
        """
        try:
            parameters_metadata = nb.metadata["times-square"].parameters
        except AttributeError:
            return cls({})

        parameters: dict[str, PageParameterSchema] = {}
        for name, schema in parameters_metadata.items():
            parameters[name] = create_and_validate_parameter_schema(
                name, schema
            )

        return cls(parameters)

    @classmethod
    def create_and_validate(cls, schemas: dict[str, dict[str, Any]]) -> Self:
        """Create a `PageParameters` instance from a mapping of parameter names
        and JSON schemas.
        """
        return cls(
            {
                name: create_and_validate_parameter_schema(name, schema)
                for name, schema in schemas.items()
            }
        )

    def __getitem__(self, key: str) -> PageParameterSchema:
        """Retrieve a parameter schema by its name."""
        return self._parameter_schemas[key]

    def __len__(self) -> int:
        """Return the number of parameters."""
        return len(self._parameter_schemas)

    def __iter__(self) -> Iterator[str]:
        """Return an iterator over the parameter keys."""
        return iter(self._parameter_schemas)

    @staticmethod
    def validate_parameter_name(name: str) -> None:
        """Validate a parameter's name.

        Parameters must be valid Python variable names, which means they must
        start with a letter and contain only letters, numbers and underscores.
        They also cannot be Python keywords.
        """
        if (
            str.isidentifier(name)
            and not keyword.iskeyword(name)
            and not keyword.issoftkeyword(name)
        ):
            return
        raise ParameterNameValidationError.for_param(name)

    def resolve_values(
        self, input_values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Resolve and validate parameter values for a notebook instance.

        Parameters
        ----------
        input_values
            A dictionary of parameter names to their values. These values may
            be incomplete if the user has not provided all the parameters.

        Returns
        -------
        dict
            A dictionary of parameter names to their resolved values
        """
        # Collect the values for each parameter; either from the request or
        # the default. Avoid extraneous parameters from the request for
        # security.
        resolved_values = {
            name: input_values.get(name, schema.default)
            for name, schema in self._parameter_schemas.items()
        }

        # Cast to the correct types
        cast_values: dict[str, Any] = {}
        for name, value in resolved_values.items():
            try:
                cast_values[name] = self[name].cast_value(value)
            except PageParameterValueCastingError as e:
                raise PageParameterError.for_param(
                    name, value, self[name]
                ) from e

        # Ensure each parameter's value is valid
        for name, value in cast_values.items():
            if not self[name].validate(value):
                raise PageParameterError.for_param(name, value, self[name])

        return cast_values
