from __future__ import annotations

from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["StringParameterSchema"]


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
        # Use repr to escape special characters and ensure that the string
        # is quoted.
        return f"{name} = {cast_value!r}"

    def create_json_value(self, value: Any) -> Any:
        return self.cast_value(value)

    def create_qs_value(self, value: Any) -> str:
        return self.cast_value(value)
