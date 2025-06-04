"""Domain models for schedule rules."""

# This module was originally developed for Semaphore (lsst-sqre/semaphore), and
# adapted here.

from __future__ import annotations

import datetime
from enum import StrEnum
from typing import Annotated, Any

import dateutil.rrule
from pydantic import (
    BaseModel,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

__all__ = [
    "ByWeekday",
    "FreqEnum",
    "ScheduleRruleset",
    "ScheduleRule",
    "WeekdayEnum",
]


class FreqEnum(StrEnum):
    """An enumeration of frequency labels for RecurringRule."""

    # These are lower-cased versions of dateutil.rrule frequency attribute
    # constants. The to_rrule_freq method transforms these labels
    # to dateutil values (integers) for use with dateutil.
    yearly = "yearly"
    monthly = "monthly"
    weekly = "weekly"
    daily = "daily"
    hourly = "hourly"
    minutely = "minutely"

    def to_rrule_freq(self) -> int:
        """Convert the frequency to an integer for use as the ``freq``
        parameter in `dateutil.rrule.rrule`.
        """
        return getattr(dateutil.rrule, self.name.upper())


class WeekdayEnum(StrEnum):
    """A enumeration of weekday names."""

    sunday = "sunday"
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"

    def to_rrule_weekday(self) -> dateutil.rrule.weekday:
        """Convert the weekday to an `dateutil.rrule.weekday` for use with the
        ``byweekday`` and ``wkst`` parameter of `dateutil.rrule.rrule`.
        """
        if self.name == "sunday":
            return dateutil.rrule.SU
        elif self.name == "monday":
            return dateutil.rrule.MO
        elif self.name == "tuesday":
            return dateutil.rrule.TU
        elif self.name == "wednesday":
            return dateutil.rrule.WE
        elif self.name == "thursday":
            return dateutil.rrule.TH
        elif self.name == "friday":
            return dateutil.rrule.FR
        return dateutil.rrule.SA


class ByWeekday(BaseModel):
    """A Pydantic model for the ``by_weekday`` field in the `RecurringRule`
    model.
    """

    day: Annotated[WeekdayEnum, Field(description="The day of the week")]

    index: Annotated[
        int | None,
        Field(
            default=None,
            description=(
                "The index of the weekday. For example, with a monthly "
                "recurrency frequency, an index of ``1`` means the first of "
                "that weekday of the month"
            ),
        ),
    ]

    def to_rrule_weekday(self) -> dateutil.rrule.weekday:
        """Convert to a `dateutil.rrule.weekday`, accounting for the index."""
        weekday = self.day.to_rrule_weekday()
        if self.index is not None:
            return weekday(self.index)
        return weekday


def _convert_to_tzinfo(v: Any) -> datetime.tzinfo:
    """Convert a timezone into a tzinfo instance."""
    if v is None:
        return datetime.UTC
    if isinstance(v, datetime.tzinfo):
        return v
    if isinstance(v, str):
        # Try to parse as timezone name
        import zoneinfo

        try:
            return zoneinfo.ZoneInfo(v)
        except Exception:
            # Fall back to UTC if parsing fails
            return datetime.UTC
    return datetime.UTC


def _convert_to_datetime(
    v: Any, default_tz: datetime.tzinfo = datetime.UTC
) -> datetime.datetime | None:
    """Convert a datetime value to a datetime.datetime, or None."""
    if v is None:
        return v
    if isinstance(v, datetime.datetime):
        # If no timezone info, assume default timezone
        if v.tzinfo is None:
            return v.replace(tzinfo=default_tz)
        return v
    if isinstance(v, str):
        # Try to parse ISO format
        try:
            dt = datetime.datetime.fromisoformat(v)
            # If no timezone info in parsed datetime, add default
            if dt.tzinfo is None:
                return dt.replace(tzinfo=default_tz)
        except ValueError:
            return None
        else:
            return dt
    return None


class ScheduleRule(BaseModel):
    """A rule to include or exclude from a recurring schedule.

    Notes
    -----
    This model is intended to be an inteferace for defining
    `dateutil.rrule.rrule` instances. In turn, rrule is an implementation
    of :rfc:`5545` (iCalendar). While the fields in this model generally match
    up to `~dateutil.rrule.rrule` parameters and :rfc:`5545` syntax, the field
    names here are slightly modified for the Times Square sidecar schema.
    """

    timezone: Annotated[
        datetime.tzinfo | None,
        Field(
            default=None,
            description=(
                "Default timezone for any datetime fields that don't contain "
                "explicit datetimes"
            ),
        ),
    ]
    date: Annotated[
        datetime.datetime | None,
        Field(
            default=None,
            description=(
                "A fixed datetime to include (or exclude) from the recurrence"
            ),
        ),
    ]
    freq: Annotated[
        FreqEnum | None,
        Field(default=None, description="Frequency of recurrence"),
    ]
    interval: Annotated[
        int,
        Field(
            default=1,
            description=(
                "The interval between each iteration. For example, if "
                "``freq`` is monthly, an interval of ``2`` means that the "
                "rule triggers every two months."
            ),
        ),
    ]
    start: Annotated[
        datetime.datetime,
        Field(
            description=(
                "The date when the repeating rule starts. If not set, the "
                "rule is assumed to start now"
            ),
            default_factory=lambda: datetime.datetime.now(datetime.UTC),
        ),
    ]
    end: Annotated[
        datetime.datetime | None,
        Field(
            default=None,
            description=(
                "Then date when this rule ends. The last recurrence is the "
                "datetime that is less than or equal to this date. If not "
                "set, the rule can recur infinitely"
            ),
        ),
    ]
    count: Annotated[
        int | None,
        Field(
            default=None,
            description=(
                "The number of occurrences of this recurring rule. The "
                "``count`` must be used exclusively of the ``end`` date field"
            ),
        ),
    ]
    week_start: Annotated[
        WeekdayEnum | None,
        Field(
            default=None,
            description="The week start day for weekly frequencies",
        ),
    ]
    by_set_position: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "Each integer specifies the occurence number within the "
                "recurrence frequency (freq). For example, with a monthly "
                "frequency, and a by_weekday of Friday, a value of ``1`` "
                "specifies the first Friday of the month. Likewise, ``-1`` "
                "specifies the last Friday of the month"
            ),
        ),
    ]
    by_month: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The months (1-12) when the recurrence happens. Use negative "
                "integers to specify an index from the end of the year"
            ),
        ),
    ]
    by_month_day: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The days of the month (1-31) when the recurrence happens. "
                "Use negative integers to specify an index from the end of "
                "the month"
            ),
        ),
    ]
    by_year_day: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The days of the year (1-366; allowing for leap years) when "
                "the recurrence happens. Use negative integers to specify a "
                "day relative to the end of the year"
            ),
        ),
    ]
    by_week: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The weeks of the year (1-52) when the recurrence happens. "
                "Use negative integers to specify a week relative to the end "
                "of the year. The definition of week matches ISO 8601: the "
                "first week of the year is the one with at least 4 days"
            ),
        ),
    ]
    by_weekday: Annotated[
        list[ByWeekday] | None,
        Field(
            default=None,
            description="The days of the week when the recurrence happens",
        ),
    ]
    by_hour: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The hours of the day (0-23) when the recurrence happens"
            ),
        ),
    ]
    by_minute: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The minutes of the hour (0-59) when the recurrence happens"
            ),
        ),
    ]
    by_second: Annotated[
        list[int] | None,
        Field(
            default=None,
            description=(
                "The seconds of the minute (0-59) when the recurrence happens"
            ),
        ),
    ]
    exclude: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Set to True to exclude these events from the schedule"
            ),
        ),
    ]

    @field_validator("timezone", mode="before")
    @classmethod
    def preprocess_timezone(cls, v: Any) -> datetime.tzinfo:
        """Convert a timezone into a tzinfo instance."""
        return _convert_to_tzinfo(v)

    @field_validator("date", "start", "end", mode="before")
    @classmethod
    def preprocess_optional_datetime(cls, v: Any) -> datetime.datetime | None:
        """Convert a datetime into a datetime.datetime, or None."""
        if v is None:
            return v
        return _convert_to_datetime(v, default_tz=datetime.UTC)

    @field_validator("by_set_position", "by_year_day")
    @classmethod
    def check_year_day_index(cls, v: list[int] | None) -> list[int] | None:
        """Validate year day indices."""
        if v is None:
            return v
        for item in v:
            if not ((1 <= item <= 366) or (-366 <= item <= -1)):
                raise ValueError(
                    "value must be in the range [1, 366] or [-366, -1]"
                )
        return v

    @field_validator("by_month")
    @classmethod
    def check_month_index(cls, v: list[int] | None) -> list[int] | None:
        """Validate month indices."""
        if v is None:
            return v
        for item in v:
            if not ((1 <= item <= 12) or (-12 <= item <= -1)):
                raise ValueError(
                    "value must be in the range [1, 12] or [-12, -1]"
                )
        return v

    @field_validator("by_month_day")
    @classmethod
    def check_month_day(cls, v: list[int] | None) -> list[int] | None:
        """Validate month day indices."""
        if v is None:
            return v
        for item in v:
            if not ((1 <= item <= 31) or (-31 <= item <= -1)):
                raise ValueError(
                    "value must be in the range [1, 31] or [-31, -1]"
                )
        return v

    @field_validator("by_week")
    @classmethod
    def check_week(cls, v: list[int] | None) -> list[int] | None:
        """Validate week indices."""
        if v is None:
            return v
        for item in v:
            if not ((1 <= item <= 52) or (-52 <= item <= -1)):
                raise ValueError(
                    "value must be in the range [1, 52] or [-52, -1]"
                )
        return v

    @field_validator("by_hour")
    @classmethod
    def check_hour(cls, v: list[int] | None) -> list[int] | None:
        """Validate hour values."""
        if v is None:
            return v
        for item in v:
            if not (0 <= item <= 23):
                raise ValueError("value must be in the range [0, 23]")
        return v

    @field_validator("by_minute")
    @classmethod
    def check_minute(cls, v: list[int] | None) -> list[int] | None:
        """Validate minute values."""
        if v is None:
            return v
        for item in v:
            if not (0 <= item <= 59):
                raise ValueError("value must be in the range [0, 59]")
        return v

    @field_validator("by_second")
    @classmethod
    def check_second(cls, v: list[int] | None) -> list[int] | None:
        """Validate second values."""
        if v is None:
            return v
        for item in v:
            if not (0 <= item <= 59):
                raise ValueError("value must be in the range [0, 59]")
        return v

    @model_validator(mode="after")
    def check_combinations(self) -> ScheduleRule:
        """Validate that fields are used together correctly.

        Notes
        -----
        Rules:

        - ``end`` and ``count`` cannot be used together.
        - ``date`` cannot be used with the recurrence settings
        - If ``date`` is none, ``freq`` must be set
        """
        if (self.date is None) and (self.freq is None):
            raise ValueError('"freq" must be set for a recurring rule.')
        if (self.end is not None) and (self.count is not None):
            raise ValueError('"end" and "count" cannot be set simultaneously.')
        if self.date is not None:
            # all recurring settings must not be set
            recurring_attributes = [
                "freq",
                "start",
                "end",
                "count",
                "week_start",
                "by_set_position",
                "by_month",
                "by_month_day",
                "by_year_day",
                "by_hour",
                "by_minute",
                "by_second",
            ]
            for attr in recurring_attributes:
                if getattr(self, attr) is not None:
                    raise ValueError(
                        '"date" cannot be used with fields for a recurring '
                        "rule."
                    )
        return self

    def to_rrule(self) -> dateutil.rrule.rrule:
        """Export to a `dateutil.rrule.rrule`."""
        if self.date is not None:
            raise RuntimeError(
                "Cannot export a fixed-date based rule as an rrule. "
                "Use to_datetime() in this case."
            )
        if self.freq is None:
            raise RuntimeError(
                'Cannot export an rrule without a "freq" field.'
            )
        return dateutil.rrule.rrule(
            freq=self.freq.to_rrule_freq(),
            dtstart=self.start if self.start else None,
            interval=self.interval,
            wkst=(
                self.week_start.to_rrule_weekday() if self.week_start else None
            ),
            until=self.end if self.end else None,
            bysetpos=self.by_set_position,
            bymonth=self.by_month,
            bymonthday=self.by_month_day,
            byyearday=self.by_year_day,
            byweekno=self.by_week,
            byweekday=(
                [w.to_rrule_weekday() for w in self.by_weekday]
                if self.by_weekday
                else None
            ),
            byhour=self.by_hour,
            byminute=self.by_minute,
            bysecond=self.by_second,
        )

    def to_datetime(self) -> datetime.datetime:
        """Export to a `datetime.datetime`."""
        if self.date is None:
            raise RuntimeError(
                "Cannot export a recurrence-based rule as a single date. "
                "Use to_rrule() in this case."
            )
        return self.date

    model_config = {"arbitrary_types_allowed": True}


class ScheduleRruleset(RootModel[list[ScheduleRule]]):
    """A Pydantic model for a list of schedule rules.

    This is used to validate and serialize/deserialize the rruleset
    JSON string.
    """

    def serialize_to_rruleset_json(self) -> str:
        """Export the ScheduleRruleset to a JSON string."""
        return self.model_dump_json()
