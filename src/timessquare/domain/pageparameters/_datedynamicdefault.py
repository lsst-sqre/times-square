from __future__ import annotations

import re
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta

__all__ = ["DYNAMIC_DATE_PATTERN", "DateDynamicDefault"]


DYNAMIC_DATE_PATTERN = re.compile(
    r"^(?:(?P<sign>[+-])(?P<offset>\d+)(?P<base>d|(?:week|month|year)_(?:start|end)))|"
    r"(?P<simple>today|yesterday|tomorrow|(?:week|month|year)_(?:start|end))$"
)
"""Pattern for dynamic date default configurations."""


class DateDynamicDefault:
    """Handler for dynamic default values for date parameters.

    Parameters
    ----------
    config_value : str
        The dynamic default value in the format defined by
        `DYNAMIC_DATE_PATTERN`. It can be a simple value like "today",
        "yesterday", "tomorrow", or a more complex expression like "+7d" or
        "-1month_start".
    """

    def __init__(self, config_value: str) -> None:
        self.config_value = config_value
        self._validate()

    def _validate(self) -> None:
        """Validate the dynamic default value format."""
        match = DYNAMIC_DATE_PATTERN.match(self.config_value)
        if not match:
            msg = f"Invalid dynamic default format: {self.config_value}"
            raise ValueError(msg)

        # Check for patterns with offset (sign + number + base)
        if (
            match.group("sign")
            and match.group("offset")
            and match.group("base")
        ):
            return

        # Check for simple patterns (today, yesterday, tomorrow, etc.)
        if match.group("simple"):
            return

        raise ValueError(
            f"Invalid dynamic default format: {self.config_value}"
        )

    def __call__(self, current_date: date | None = None) -> date:
        """Compute the dynamic default date.

        Parameters
        ----------
        current_date
            The reference date to use for calculations. If None, uses today
            in UTC.

        Returns
        -------
        date
            The computed date based on the dynamic default value.
        """
        if current_date is None:
            current_date = datetime.now(tz=UTC).date()

        # Handle simple cases
        if self.config_value == "today":
            return current_date
        elif self.config_value == "yesterday":
            return self._subtract_days(current_date, 1)
        elif self.config_value == "tomorrow":
            return self._add_days(current_date, 1)

        # Handle complex patterns
        return self._compute_complex_date(current_date)

    def _compute_complex_date(self, current_date: date) -> date:  # noqa: C901
        """Compute dates for complex patterns."""
        match = DYNAMIC_DATE_PATTERN.match(self.config_value)
        if not match:
            raise ValueError(
                f"Invalid dynamic default format: {self.config_value}"
            )

        # Check if it's a simple pattern (no offset)
        if match.group("simple"):
            base = match.group("simple")
            offset = 0
        else:
            # Complex pattern with offset
            base = match.group("base")
            offset = int(match.group("offset")) if match.group("offset") else 0
            sign = match.group("sign")

            if sign == "-":
                offset = -offset

        match base:
            case "d":
                return self._add_days(current_date, offset)
            case "week_start":
                return self._compute_week_start(current_date, offset)
            case "week_end":
                return self._compute_week_end(current_date, offset)
            case "month_start":
                return self._compute_month_start(current_date, offset)
            case "month_end":
                return self._compute_month_end(current_date, offset)
            case "year_start":
                return self._compute_year_start(current_date, offset)
            case "year_end":
                return self._compute_year_end(current_date, offset)
            case _:
                raise ValueError(
                    f"Unsupported dynamic default: {self.config_value}"
                )

    def _compute_week_start(self, current_date: date, offset: int) -> date:
        """Compute week start date."""
        week_start = current_date - timedelta(days=current_date.weekday())
        if offset != 0:
            week_start = self._add_days(week_start, offset * 7)
        return week_start

    def _compute_week_end(self, current_date: date, offset: int) -> date:
        """Compute week end date."""
        days_to_end = 6 - current_date.weekday()
        week_end = current_date + timedelta(days=days_to_end)
        if offset != 0:
            week_end = self._add_days(week_end, offset * 7)
        return week_end

    def _compute_month_start(self, current_date: date, offset: int) -> date:
        """Compute month start date."""
        month_start = current_date.replace(day=1)
        if offset != 0:
            month_start = self._add_months(month_start, offset)
        return month_start

    def _compute_month_end(self, current_date: date, offset: int) -> date:
        """Compute month end date."""
        # Get last day of current month
        last_day = monthrange(current_date.year, current_date.month)[1]
        month_end = current_date.replace(day=last_day)
        if offset != 0:
            # Add months, then get the last day of that month
            month_end = self._add_months(month_end.replace(day=1), offset)
            last_day = monthrange(month_end.year, month_end.month)[1]
            month_end = month_end.replace(day=last_day)
        return month_end

    def _compute_year_start(self, current_date: date, offset: int) -> date:
        """Compute year start date."""
        year_start = current_date.replace(month=1, day=1)
        if offset != 0:
            year_start = year_start.replace(year=year_start.year + offset)
        return year_start

    def _compute_year_end(self, current_date: date, offset: int) -> date:
        """Compute year end date."""
        year_end = current_date.replace(month=12, day=31)
        if offset != 0:
            year_end = year_end.replace(year=year_end.year + offset)
        return year_end

    @staticmethod
    def _add_days(base_date: date, days: int) -> date:
        """Add days to a date."""
        return base_date + timedelta(days=days)

    @staticmethod
    def _subtract_days(base_date: date, days: int) -> date:
        """Subtract days from a date."""
        return base_date - timedelta(days=days)

    @staticmethod
    def _add_months(base_date: date, months: int) -> date:
        """Add months to a date."""
        new_month = base_date.month + months
        new_year = base_date.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1

        # Handle day overflow (e.g., Jan 31 + 1 month = Feb 28/29)
        try:
            return base_date.replace(year=new_year, month=new_month)
        except ValueError:
            # Day doesn't exist in target month, use last day of month
            last_day = monthrange(new_year, new_month)[1]
            return base_date.replace(
                year=new_year, month=new_month, day=last_day
            )
