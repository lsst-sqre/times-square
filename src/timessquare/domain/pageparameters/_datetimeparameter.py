from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._schemabase import PageParameterSchema

__all__ = ["DatetimeParameterSchema"]


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
