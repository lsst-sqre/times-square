"""Domain model for an execution schedule."""

from __future__ import annotations

import datetime
from functools import lru_cache

import dateutil.rrule

from .schedulerule import ScheduleRruleset

__all__ = ["RunSchedule"]


class RunSchedule:
    """A domain model for an page's run schedule.

    Parameters
    ----------
    rruleset_str
        A JSON-serialized string representing the rruleset.
    enabled
        Whether the schedule is enabled.

    Notes
    -----
    The rruleset serialization is not built into dateutil
    (https://github.com/dateutil/dateutil/issues/856), but we use a
    serialization strategy also published as a gist
    https://gist.github.com/maxfire2008/096fd5f55c9d79a11d41769d58e8bca1.
    """

    def __init__(self, rruleset_str: str, *, enabled: bool) -> None:
        self._rruleset_str = rruleset_str
        self.enabled = enabled

    @property
    def schedule_rruleset(self) -> str:
        """The schedule rruleset as a JSON string."""
        return self._rruleset_str

    @property
    def rruleset(self) -> dateutil.rrule.rruleset:
        """The schedule rruleset as a dateutil rruleset object."""
        return _deserialize_rruleset_str(self._rruleset_str)

    def next(
        self, after: datetime.datetime | None
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
def _deserialize_rruleset_str(
    rruleset_str: str,
) -> dateutil.rrule.rruleset:
    """Deserialize a JSON string into a list of ScheduleRule objects."""
    schedule_rules = ScheduleRruleset.model_validate_json(rruleset_str)
    rset = dateutil.rrule.rruleset(cache=True)
    for rule in schedule_rules.root:
        if rule.date is not None:
            if rule.exclude:
                rset.exdate(rule.to_datetime())
            else:
                rset.rdate(rule.to_datetime())
        elif rule.exclude:
            rset.exrule(rule.to_rrule())
        else:
            rset.rrule(rule.to_rrule())

    return rset
