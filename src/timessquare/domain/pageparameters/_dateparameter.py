from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["DateParameterSchema"]


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

    @property
    def default(self) -> date:
        if "X-Dynamic-Default" in self.validator.schema:
            return datetime.now(tz=UTC).date()
        return self.cast_value(self.schema["default"])
