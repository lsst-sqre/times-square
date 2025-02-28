"""Domain of page parameters."""

from __future__ import annotations

import abc
import json
import keyword
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
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

__all__ = [
    "BooleanParameterSchema",
    "DateParameterSchema",
    "DatetimeParameterSchema",
    "IntegerParameterSchema",
    "NumberParameterSchema",
    "PageParameterSchema",
    "PageParameters",
    "StringParameterSchema",
]


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


@dataclass(kw_only=True)
class PageParameterSchema(abc.ABC):
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
        """Get the schema's default value as the native Python type."""
        return self.cast_value(self.schema["default"])

    def __str__(self) -> str:
        return json.dumps(self.schema, sort_keys=True, indent=2)

    def validate(self, v: Any) -> bool:
        """Validate a parameter value."""
        # The JSON schema validator requires a JSON-compatible value.
        # For example, a date parameter would be a string in ISO 8601 format
        # rather than a Python `date` object.
        json_value = self.create_json_value(v)
        return self.validator.is_valid(json_value)

    @abc.abstractmethod
    def cast_value(self, v: Any) -> Any:
        """Cast a value to its Python type."""
        raise NotImplementedError

    def create_python_imports(self) -> list[str]:
        """Create Python import statements needed for the python assignment."""
        return []

    @abc.abstractmethod
    def create_python_assignment(self, name: str, value: Any) -> str:
        """Create a Python assignment statement for a parameter.

        Parameters
        ----------
        name
            The parameter name, which is also the Python variable name.
        value
            The parameter value. This value is cast to the Python type.

        Return
        ------
        str
            The Python assignment statement. For example, `name = value`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def create_json_value(self, value: Any) -> Any:
        """Convert the value to a JSON-compatible value.

        This is used to create the JSON representation of the parameter value
        in the notebook's metadata (``metadata.times-square.values``).

        Parameters
        ----------
        value
            The parameter value.

        Return
        ------
        Any
            The JSON-compatible value
        """
        raise NotImplementedError

    @abc.abstractmethod
    def create_qs_value(self, value: Any) -> str:
        """Convert the value to a query string-compatible string.

        This representation can be used to generate the URL query string that
        would have signaled the parameter value. It is also used to generate
        the cache key for the page instance.

        Parameters
        ----------
        value
            The parameter value.

        Return
        ------
        str
            The query string-compatible value
        """
        raise NotImplementedError


@dataclass(kw_only=True)
class StringParameterSchema(PageParameterSchema):
    """A string-type parameter schema."""

    def cast_value(self, v: Any) -> str:
        """Cast a value to its Python type."""
        try:
            return str(v)
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "string") from e

    def create_python_assignment(self, name: str, value: Any) -> str:
        cast_value = self.cast_value(value)
        return f'{name} = "{cast_value}"'

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value)

    def create_qs_value(self, value: Any) -> str:
        return self.cast_value(value)


class IntegerParameterSchema(PageParameterSchema):
    """An integer-type parameter schema."""

    def cast_value(self, v: Any) -> int:
        """Cast a value to its Python type."""
        try:
            return int(v)
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "integer") from e

    def create_python_assignment(self, name: str, value: Any) -> str:
        cast_value = self.cast_value(value)
        return f"{name} = {cast_value}"

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value)

    def create_qs_value(self, value: Any) -> str:
        return str(self.cast_value(value))


class NumberParameterSchema(PageParameterSchema):
    """A number-type parameter schema."""

    def cast_value(self, v: Any) -> float | int:
        """Cast a value to its Python type."""
        try:
            if isinstance(v, str):
                if "." in v:
                    return float(v)
                else:
                    return int(v)
            elif isinstance(v, int | float):
                return v
            return float(v)
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "number") from e

    def create_python_assignment(self, name: str, value: Any) -> str:
        cast_value = self.cast_value(value)
        return f"{name} = {cast_value}"

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value)

    def create_qs_value(self, value: Any) -> str:
        return str(self.cast_value(value))


class BooleanParameterSchema(PageParameterSchema):
    """A boolean-type parameter schema."""

    def cast_value(self, v: Any) -> bool:
        """Cast a value to its Python type."""
        if isinstance(v, str):
            if v.lower() == "true":
                return True
            elif v.lower() == "false":
                return False
            else:
                raise PageParameterValueCastingError.for_value(v, "boolean")
        elif isinstance(v, bool):
            return v
        raise PageParameterValueCastingError.for_value(v, "boolean")

    def create_python_assignment(self, name: str, value: Any) -> str:
        cast_value = self.cast_value(value)
        return f"{name} = {cast_value}"

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value)

    def create_qs_value(self, value: Any) -> str:
        # The query string follows the JSON format, so lowercase true/false.
        return str(self.cast_value(value)).lower()


class DateParameterSchema(PageParameterSchema):
    """A date-type parameter schema."""

    def cast_value(self, v: Any) -> date:
        """Cast a value to its Python type."""
        try:
            # Parse an ISO 8601 date string
            if isinstance(v, str):
                return date.fromisoformat(v)
            elif isinstance(v, date):
                return v
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "date") from e

        raise PageParameterValueCastingError.for_value(v, "date")

    def create_python_imports(self) -> list[str]:
        return ["import datetime"]

    def create_python_assignment(self, name: str, value: Any) -> str:
        date_value = self.cast_value(value)
        str_value = date_value.isoformat()
        return f'{name} = datetime.date.fromisoformat("{str_value}")'

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value).isoformat()

    def create_qs_value(self, value: Any) -> str:
        return self.cast_value(value).isoformat()


class DatetimeParameterSchema(PageParameterSchema):
    """A datetime-type parameter schema that is timezone-aware."""

    def cast_value(self, v: Any) -> datetime:
        """Cast a value to its Python type."""
        date_value = self._cast_to_datetime(v)
        if date_value.tzinfo is None:
            # Force the timezone to UTC if naieve
            date_value = date_value.replace(tzinfo=UTC)
        return date_value

    def _cast_to_datetime(self, v: Any) -> datetime:
        try:
            # Parse an ISO 8601 datetime string
            if isinstance(v, str):
                return datetime.fromisoformat(v)
            elif isinstance(v, datetime):
                return v
        except Exception as e:
            raise PageParameterValueCastingError.for_value(
                v, "datetime"
            ) from e

        raise PageParameterValueCastingError.for_value(v, "datetime")

    def create_python_imports(self) -> list[str]:
        return ["import datetime"]

    def create_python_assignment(self, name: str, value: Any) -> str:
        date_value = self.cast_value(value)
        str_value = date_value.isoformat()
        return f'{name} = datetime.datetime.fromisoformat("{str_value}")'

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value).isoformat()

    def create_qs_value(self, value: Any) -> str:
        return self.cast_value(value).isoformat()
