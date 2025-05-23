from __future__ import annotations

from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["IntegerParameterSchema"]


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
