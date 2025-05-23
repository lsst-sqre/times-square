from __future__ import annotations

from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["NumberParameterSchema"]


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
