"""Domain of page parameters."""

from __future__ import annotations

import json
import keyword
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
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

PARAMETER_NAME_PATTERN = re.compile(
    r"^"
    r"[a-zA-Z]"  # initial characters are letters only
    r"[_a-zA-Z0-9]*$"  # following characters are letters and numbers
    r"$"
)
"""Regular expression that matches a valid parameter name."""


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
            parameters[name] = PageParameterSchema.create_and_validate(
                name, schema
            )

        return cls(parameters)

    def __getitem__(self, key: str) -> Any:
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
        if PARAMETER_NAME_PATTERN.match(name) is None:
            raise ParameterNameValidationError.for_param(name)
        if keyword.iskeyword(name):
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

    def stringify_values(self, values: Mapping[str, Any]) -> dict[str, str]:
        """Stringify parameter values for insertion into notebook code."""
        # Using repr ensures strings are quoted. But is this the best approach?
        return {name: repr(value) for name, value in values.items()}

    def create_code_template(self, values: Mapping[str, Any]) -> str:
        """Create a Jinja-templated source cell value that sets Python
        variables for each parameter to their values.
        """
        sorted_variables = sorted(values.keys())
        code_lines = [
            f"{variable_name} = {{{{ params.{variable_name} }}}}"
            for variable_name in sorted_variables
        ]
        code_lines.insert(0, "# Parameters")
        return "\n".join(code_lines)


@dataclass
class PageParameterSchema:
    """The domain model for a page parameter's JSON schema, which is a template
    variable in a page's notebook (`PageModel`).
    """

    validator: Draft202012Validator
    """Parameter value validator (based on `json_schema`)."""

    @classmethod
    def create(cls, json_schema: dict[str, Any]) -> PageParameterSchema:
        """Create a PageParameterSchema given a JSON Schema.

        Note that this method does not validate the schema. If the schema is
        being instantiated from an external source, run the
        `create_and_validate` constructor instead.
        """
        return cls(validator=Draft202012Validator(json_schema))

    @classmethod
    def create_and_validate(
        cls, name: str, json_schema: dict[str, Any]
    ) -> PageParameterSchema:
        try:
            Draft202012Validator.check_schema(json_schema)
        except jsonschema.exceptions.SchemaError as e:
            message = f"The schema for the {name} parameter is invalid.\n\n{e}"
            raise ParameterSchemaError.for_param(name, message) from e

        if "default" not in json_schema:
            raise ParameterDefaultMissingError.for_param(name)

        instance = cls.create(json_schema)
        if not instance.validate(json_schema["default"]):
            raise ParameterDefaultInvalidError.for_param(
                name, json_schema["default"]
            )

        return instance

    @property
    def schema(self) -> dict[str, Any]:
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

    def cast_value(self, v: Any) -> Any:  # noqa: C901 PLR0912
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
                        raise PageParameterValueCastingError.for_value(
                            v, schema_type
                        )
                else:
                    return v
            else:
                raise PageParameterValueCastingError.for_value(v, schema_type)
        except ValueError as e:
            raise PageParameterValueCastingError.for_value(
                v, schema_type
            ) from e
