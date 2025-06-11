from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from timessquare.exceptions import PageParameterValueCastingError

from ._datedynamicdefault import DateDynamicDefault
from ._schemabase import PageParameterSchema

__all__ = ["DayObsParameterSchema"]


class DayObsParameterSchema(PageParameterSchema):
    """A parameter schema for the custom Rubin DayObs format.

    DayObs is defined as the date in the UTC-12 timezone. It's string
    representation formatted is YYYYMMDD. Times Square parameters validate
    dayobs parameters as int types in notebook code.
    integers.
    """

    tz = timezone(-timedelta(hours=12))
    """The timezone for DayObs parameters, UTC-12."""

    @property
    def strict_schema(self) -> dict[str, Any]:
        """Get the JSON schema without the custom format."""
        schema = super().strict_schema
        # Add a basic regex pattern to validate the DayObs format
        schema["pattern"] = r"^\d{8}$"
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

    def cast_value(self, v: Any) -> int:
        """Cast a value to its Python type."""
        try:
            # Parse a YYYYMMDD string, integer, date object, or datetime object
            if isinstance(v, str):
                return self._cast_string(v)
            elif isinstance(v, int):
                return self._cast_integer(v)
            elif isinstance(v, datetime):
                # Check datetime before date because of inheritance
                return self._cast_datetime(v)
            elif isinstance(v, date):
                return self._cast_date(v)
            else:
                raise PageParameterValueCastingError.for_value(v, "date")
        except Exception as e:
            raise PageParameterValueCastingError.for_value(v, "date") from e

    def _cast_string(self, v: str) -> int:
        """Cast a string value to the DayObs format."""
        match = re.match(r"^\d{8}$", v)
        if not match:
            raise ValueError(f"Invalid YYYYMMDD format: {v}")

        year = int(v[:4])
        month = int(v[4:6])
        day = int(v[6:8])
        return self._cast_date(date(year, month, day))

    def _cast_integer(self, v: int) -> int:
        """Cast an integer value to the DayObs format."""
        return self._cast_string(str(v))

    def _cast_date(self, v: date) -> int:
        """Cast a date object to the DayObs format."""
        return int(v.strftime("%Y%m%d"))

    def _cast_datetime(self, v: datetime) -> int:
        """Cast a datetime object to the DayObs format."""
        if v.tzinfo is not None:
            # Convert to UTC-12 timezone
            v = v.astimezone(self.tz)
        else:
            # If no timezone info, assume it's in UTC-12
            v = v.replace(tzinfo=self.tz)
        return self._cast_date(v.date())

    def create_python_assignment(self, name: str, value: Any) -> str:
        int_value = self.cast_value(value)
        return f"{name} = {int_value}"

    def create_json_value(self, value: Any) -> str:
        return str(self.cast_value(value))

    def create_qs_value(self, value: Any) -> str:
        return str(self.cast_value(value))

    @property
    def default(self) -> str:
        if "X-Dynamic-Default" in self.schema:
            dynamic_default = DateDynamicDefault(
                self.schema["X-Dynamic-Default"]
            )
            return str(
                self.cast_value(
                    dynamic_default(datetime.now(tz=self.tz).date())
                )
            )
        return str(self.cast_value(self.schema["default"]))
