"""Domain model for an execution schedule."""

from __future__ import annotations

import datetime
from functools import lru_cache

import dateutil.rrule

from .schedulerule import (
    ScheduleDate,
    ScheduleFromDate,
    ScheduleRule,
    ScheduleRules,
)

__all__ = ["RunSchedule"]


class RunSchedule:
    """A domain model for a page's run schedule.

    Parameters
    ----------
    schedule_json
        A JSON-serialized string representing the schedule rules.
    enabled
        Whether the schedule is enabled.
    """

    def __init__(self, schedule_json: str, *, enabled: bool) -> None:
        self._schedule_json = schedule_json
        self.enabled = enabled

    @property
    def schedule_json(self) -> str:
        """The schedule rruleset as a JSON string."""
        return self._schedule_json

    @property
    def rules(self) -> ScheduleRules:
        """The schedule rruleset as a ScheduleRruleset object.

        This property is primarily for testing.
        """
        return ScheduleRules.model_validate_json(self._schedule_json)

    @property
    def rruleset(self) -> dateutil.rrule.rruleset:
        """The schedule rruleset as a dateutil rruleset object."""
        return _deserialize_schedule_json(self._schedule_json)

    def next(
        self,
        after: datetime.datetime | None,
    ) -> datetime.datetime | None:
        """Get the next scheduled time after a given datetime.

        Parameters
        ----------
        after
            The datetime after which to find the next scheduled time.
            Defalts to now.

        Returns
        -------
        datetime.datetime | None
            The next scheduled time, or None if no more times are scheduled
            or the schedule is disabled. Times are scheduled on the minute.
        """
        if self.enabled is False:
            return None
        if after is None:
            after_dt = datetime.datetime.now(datetime.UTC)
        else:
            after_dt = after.astimezone(datetime.UTC)
        next_dt = self.rruleset.after(after_dt, inc=False)

        if next_dt is None:
            return None

        # Ensure that scheduled times aren't more granular than minutes
        # to avoid issues with scheduling tasks hyper-frequently.
        return next_dt.replace(second=0, microsecond=0)


# This function is cached to avoid re-parsing the same JSON string. However
# it isn't part of the next property for RunSchedule because we want to
# avoid a memory leak when using lru_cache in conjunction with methods.
@lru_cache
def _deserialize_schedule_json(
    rruleset_json: str,
) -> dateutil.rrule.rruleset:
    """Deserialize a JSON string into a list of ScheduleRule objects."""
    schedule_rules = ScheduleRules.model_validate_json(rruleset_json)
    rset = dateutil.rrule.rruleset(cache=True)
    for rule in schedule_rules.root:
        if isinstance(rule, ScheduleDate):
            if rule.exclude:
                rset.exdate(rule.date)
            else:
                rset.rdate(rule.date)
        elif isinstance(rule, (ScheduleRule, ScheduleFromDate)):
            if rule.exclude:
                rset.exrule(rule.to_rrule())
            else:
                rset.rrule(rule.to_rrule())
        else:
            raise TypeError(
                f"Unexpected rule type: {type(rule)}. "
                "Expected ScheduleDate, ScheduleRule, or ScheduleFromDate."
            )

    return rset
