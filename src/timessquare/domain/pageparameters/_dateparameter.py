from __future__ import annotations

from datetime import date
from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._datedynamicdefault import DateDynamicDefault
from ._schemabase import PageParameterSchema

__all__ = ["DateParameterSchema"]


class DateParameterSchema(PageParameterSchema):
    """A date-type parameter schema."""

    def validate_default(self) -> bool:
        """Validate the default value for the parameter.

        Returns
        -------
        bool
            True if the default is valid, False otherwise.
        """
        if "X-Dynamic-Default" in self.schema:
            try:
                DateDynamicDefault(self.schema["X-Dynamic-Default"])
            except ValueError:
                return False
            else:
                return True
        elif "default" in self.schema:
            try:
                self.cast_value(self.schema["default"])
            except PageParameterValueCastingError:
                return False
            else:
                return True
        else:
            return False

    def cast_value(self, v: Any) -> date:
        """Cast a value to its Python type."""
        try:
            # Parse an ISO 8601 date string
            if isinstance(v, str):
                return date.fromisoformat(v)
            elif isinstance(v, date):
                return v
            else:
                raise PageParameterValueCastingError.for_value(v, "date")
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "date") from e

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
        if "X-Dynamic-Default" in self.schema:
            dynamic_default = DateDynamicDefault(
                self.schema["X-Dynamic-Default"]
            )
            return dynamic_default()
        return self.cast_value(self.schema["default"])
