"""Domain models for schedule rules."""

# This module was originally developed for Semaphore (lsst-sqre/semaphore), and
# adapted here.

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self

import dateutil.rrule
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Discriminator,
    Field,
    RootModel,
    Tag,
    field_validator,
    model_validator,
)

__all__ = [
    "ByWeekday",
    "FreqEnum",
    "ScheduleDate",
    "ScheduleFromDate",
    "ScheduleRule",
    "ScheduleRuleBase",
    "ScheduleRules",
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


def ensure_list(value: Any) -> Any:
    """Ensure that the value is a list (before validator)."""
    if value is None:
        return None
    if not isinstance(value, list):
        return [value]
    else:
        return value


def ensure_byweekday_object(value: Any) -> Any:
    """Convert strings for days of the week to `ByWeekday` objects.
    (before validator).

    This is used to validate the `weekday` field in the `ScheduleRule` model.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        value = [value]

    values = []
    for item in value:
        if isinstance(item, dict):
            values.append(item)
        elif isinstance(item, str):
            # If an integer is provided, create a ByWeekday with that index
            values.append({"day": item})
        else:
            raise ValueError(  # noqa: TRY004
                "value must be a list of ByWeekday objects or strings "
                "representing the day of the week"
            )
    return values


def ensure_timezone_aware(value: datetime) -> datetime:
    """Ensure that the datetime is timezone aware, defaulting to UTC.

    Use as an after-validator.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ScheduleRuleBase(BaseModel):
    """Base class for scheduling rules."""

    exclude: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Set to True to exclude these events from the schedule"
            ),
        ),
    ]


class ScheduleDate(ScheduleRuleBase):
    """A scheduling rule for a fixed date."""

    date: Annotated[
        datetime,
        Field(
            description=(
                "A fixed datetime to include (or exclude) from the schedule."
            ),
        ),
        AfterValidator(ensure_timezone_aware),
    ]


class ScheduleRule(ScheduleRuleBase):
    """A rule to include or exclude from a recurring schedule.

    Notes
    -----
    This model is intended to be an inteferace for defining
    `dateutil.rrule.rrule` instances. In turn, rrule is an implementation
    of :rfc:`5545` (iCalendar). While the fields in this model generally match
    up to `~dateutil.rrule.rrule` parameters and :rfc:`5545` syntax, the field
    names here are slightly modified for the Times Square sidecar schema.
    """

    freq: Annotated[
        FreqEnum,
        Field(description="Frequency of recurrence"),
    ]

    week_start: Annotated[
        WeekdayEnum,
        Field(
            default=WeekdayEnum.monday,
            description="The week start day for weekly frequencies.",
        ),
    ]

    set_position: Annotated[
        list[int] | None,
        Field(
            description=(
                "Each integer specifies the occurence number within the "
                "recurrence frequency (freq). For example, with a monthly "
                "frequency, and a by_weekday of Friday, a value of ``1`` "
                "specifies the first Friday of the month. Likewise, ``-1`` "
                "specifies the last Friday of the month"
            ),
        ),
        BeforeValidator(ensure_list),
    ] = None

    month: Annotated[
        list[int] | None,
        Field(
            description=(
                "The months (1-12) when the recurrence happens. Use negative "
                "integers to specify an index from the end of the year"
            ),
        ),
        BeforeValidator(ensure_list),
    ] = None

    day_of_month: Annotated[
        list[int] | None,
        Field(
            description=(
                "The days of the month (1-31) when the recurrence happens. "
                "Use negative integers to specify an index from the end of "
                "the month"
            ),
        ),
        BeforeValidator(ensure_list),
    ] = None

    day_of_year: Annotated[
        list[int] | None,
        Field(
            description=(
                "The days of the year (1-366; allowing for leap years) when "
                "the recurrence happens. Use negative integers to specify a "
                "day relative to the end of the year"
            ),
        ),
        BeforeValidator(ensure_list),
    ] = None

    week: Annotated[
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
        BeforeValidator(ensure_list),
    ]

    weekday: Annotated[
        list[ByWeekday] | None,
        Field(
            description="The days of the week when the recurrence happens",
        ),
        BeforeValidator(ensure_list),
        BeforeValidator(ensure_byweekday_object),
    ] = None

    hour: Annotated[
        list[int],
        Field(
            description=(
                "The hours of the day (0-23) when the recurrence happens"
            ),
            default_factory=lambda: [0],
        ),
        BeforeValidator(ensure_list),
    ]

    minute: Annotated[
        list[int],
        Field(
            description=(
                "The minutes of the hour (0-59) when the recurrence happens"
            ),
            default_factory=lambda: [0],
        ),
        BeforeValidator(ensure_list),
    ]

    second: Annotated[
        int,
        Field(
            description=(
                "The second of the minute (0-59) when the recurrence happens."
            ),
            ge=0,
            le=59,
        ),
    ] = 0

    @field_validator("day_of_year", mode="after")
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

    @field_validator("month", mode="after")
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

    @field_validator("day_of_month", mode="after")
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

    @field_validator("week", mode="after")
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

    @field_validator("hour", mode="after")
    @classmethod
    def check_hour(cls, v: list[int] | None) -> list[int] | None:
        """Validate hour values."""
        if v is None:
            return v
        for item in v:
            if not (0 <= item <= 23):
                raise ValueError("value must be in the range [0, 23]")
        return v

    @field_validator("minute", mode="after")
    @classmethod
    def check_minute(cls, v: list[int] | None) -> list[int] | None:
        """Validate minute values."""
        if v is None:
            return v
        for item in v:
            if not (0 <= item <= 59):
                raise ValueError("value must be in the range [0, 59]")
        return v

    def to_rrule(self) -> dateutil.rrule.rrule:
        """Export to a `dateutil.rrule.rrule`."""
        return dateutil.rrule.rrule(
            freq=self.freq.to_rrule_freq(),
            dtstart=datetime.now(tz=UTC),  # Default start time
            wkst=(
                self.week_start.to_rrule_weekday() if self.week_start else None
            ),
            bysetpos=self.set_position,
            bymonth=self.month,
            bymonthday=self.day_of_month,
            byyearday=self.day_of_year,
            byweekno=self.week,
            byweekday=(
                [w.to_rrule_weekday() for w in self.weekday]
                if self.weekday
                else None
            ),
            byhour=self.hour,
            byminute=self.minute,
            bysecond=self.second,
        )

    model_config = {"arbitrary_types_allowed": True}


class ScheduleFromDate(ScheduleRuleBase):
    """A schedule rule that repeats from a specific date."""

    start: Annotated[
        datetime,
        Field(
            description=("The date when the repeating rule starts."),
        ),
        AfterValidator(ensure_timezone_aware),
    ]

    freq: Annotated[
        FreqEnum,
        Field(description="Frequency of recurrence"),
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
            ge=1,
        ),
    ]

    end: Annotated[
        datetime | None,
        Field(
            default=None,
            description=(
                "Then date when this rule ends. The last recurrence is the "
                "datetime that is less than or equal to this date. If not "
                "set, the rule can recur infinitely"
            ),
        ),
        AfterValidator(ensure_timezone_aware),
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

    @model_validator(mode="after")
    def check_combinations(self) -> Self:
        """Validate that fields are used together correctly.

        Notes
        -----
        Rules:

        - ``end`` and ``count`` cannot be used together.
        """
        if (self.end is not None) and (self.count is not None):
            raise ValueError('"end" and "count" cannot be set simultaneously.')
        return self

    def to_rrule(self) -> dateutil.rrule.rrule:
        """Export to a `dateutil.rrule.rrule`."""
        return dateutil.rrule.rrule(
            freq=self.freq.to_rrule_freq(),
            dtstart=self.start,
            interval=self.interval,
            until=self.end if self.end else None,
            count=self.count,
            bysecond=0,
        )

    model_config = {"arbitrary_types_allowed": True}


def schedule_discriminator(v: Any) -> str:
    """Discriminator function for schedule rules."""
    if isinstance(v, dict):
        if "date" in v:
            return "date"
        elif "start" in v:
            return "from_date"
        else:
            return "rule"

    # For already instantiated objects
    if hasattr(v, "date"):
        return "date"
    elif hasattr(v, "start"):
        return "from_date"
    else:
        # Default case for ScheduleRule
        return "rule"


# Create the discriminated union type
ScheduleItem = Annotated[
    (
        Annotated[ScheduleDate, Tag("date")]
        | Annotated[ScheduleFromDate, Tag("from_date")]
        | Annotated[ScheduleRule, Tag("rule")]
    ),
    Discriminator(schedule_discriminator),
]


class ScheduleRules(RootModel[list[ScheduleItem]]):
    """A Pydantic model for a list of schedule rules.

    This is used to validate and serialize/deserialize the rruleset
    JSON string.
    """

    def serialize_to_json(self) -> str:
        """Export the ScheduleRruleset to a JSON string."""
        return self.model_dump_json(exclude_none=False)
