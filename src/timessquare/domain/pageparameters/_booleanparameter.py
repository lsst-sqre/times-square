from __future__ import annotations

from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["BooleanParameterSchema"]


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
