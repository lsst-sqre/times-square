from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(kw_only=True)
class PageParameterSchema(abc.ABC):
    """The domain model for a page parameter's JSON schema, which is a template
    variable in a page's notebook (`PageModel`).
    """

    validator: Draft202012Validator
    """Parameter value validator (based on `json_schema`)."""

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

    def validate_default(self) -> bool:
        """Validate the default value for the parameter.

        Returns
        -------
        bool
            True if the default is valid, False otherwise.
        """
        return self.validate(self.default)

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
