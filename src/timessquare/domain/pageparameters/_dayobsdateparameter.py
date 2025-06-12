from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._datedynamicdefault import DateDynamicDefault
from ._schemabase import PageParameterSchema

__all__ = ["DayObsDateParameterSchema"]


class DayObsDateParameterSchema(PageParameterSchema):
    """A parameter schema for the custom Rubin DayObs date format with dashes.

    DayObsDate is defined as a date in the UTC-12 timezone with the string
    representation formatted as YYYY-MM-DD. Times Square parameters validate
    dayobs-date parameters as strings, but the Python assignment returns a
    datetime.date instance.
    """

    tz = timezone(-timedelta(hours=12))
    """The timezone for DayObs parameters, UTC-12."""

    @property
    def strict_schema(self) -> dict[str, Any]:
        """Get the JSON schema without the custom format."""
        schema = super().strict_schema
        # Add a basic regex pattern to validate the YYYY-MM-DD format
        schema["pattern"] = r"^\d{4}-\d{2}-\d{2}$"
        return schema

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
            # Parse a YYYY-MM-DD string, date object, or datetime object
            if isinstance(v, str):
                return self._cast_string(v)
            elif isinstance(v, datetime):
                # Check datetime before date because of inheritance
                return self._cast_datetime(v)
            elif isinstance(v, date):
                return self._cast_date(v)
            else:
                raise PageParameterValueCastingError.for_value(v, "date")
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "date") from e

    def _cast_string(self, v: str) -> date:
        """Cast a string value to the date format."""
        match = re.match(r"^\d{4}-\d{2}-\d{2}$", v)
        if not match:
            raise ValueError(f"Invalid YYYY-MM-DD format: {v}")

        year = int(v[:4])
        month = int(v[5:7])
        day = int(v[8:10])
        return date(year, month, day)

    def _cast_date(self, v: date) -> date:
        """Cast a date object directly (no conversion needed)."""
        return v

    def _cast_datetime(self, v: datetime) -> date:
        """Cast a datetime object to the DayObs date format."""
        if v.tzinfo is not None:
            # Convert to UTC-12 timezone
            v = v.astimezone(self.tz)
        else:
            # If no timezone info, assume it's in UTC-12
            v = v.replace(tzinfo=self.tz)
        return v.date()

    def create_python_imports(self) -> list[str]:
        return ["import datetime"]

    def create_python_assignment(self, name: str, value: Any) -> str:
        date_value = self.cast_value(value)
        str_value = date_value.isoformat()
        return f'{name} = datetime.date.fromisoformat("{str_value}")'

    def create_json_value(self, value: Any) -> str:
        return self.cast_value(value).isoformat()

    def create_qs_value(self, value: Any) -> str:
        return self.cast_value(value).isoformat()

    @property
    def default(self) -> date:
        if "X-Dynamic-Default" in self.schema:
            dynamic_default = DateDynamicDefault(
                self.schema["X-Dynamic-Default"]
            )
            return dynamic_default(datetime.now(tz=self.tz).date())
        return self.cast_value(self.schema["default"])
