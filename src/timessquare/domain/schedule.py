"""Domain model for an execution schedule."""

from __future__ import annotations

import datetime
import json
from typing import Self

import dateutil.rrule

__all__ = ["ExecutionSchedule"]


class ExecutionSchedule:
    """A domain model for an execution schedule.

    Attributes
    ----------
    rruleset
        The recurrence rule set for the schedule.
    enabled
        Whether the schedule is enabled.

    Notes
    -----
    The rruleset serialization is not built into dateutil
    (https://github.com/dateutil/dateutil/issues/856), but we use a
    serialization strategy also published as a gist
    https://gist.github.com/maxfire2008/096fd5f55c9d79a11d41769d58e8bca1.
    """

    def __init__(
        self, rruleset: dateutil.rrule.rruleset, *, enabled: bool
    ) -> None:
        self.rruleset = rruleset
        self.enabled = enabled

    @classmethod
    def from_json_str(cls, json_str: str, *, enabled: bool) -> Self:
        """Create an ExecutionSchedule from a JSON string.

        Parameters
        ----------
        json_str
            The JSON string representing the schedule.
        enabled
            Whether the schedule is enabled.

        Returns
        -------
        ExecutionSchedule
            An instance of ExecutionSchedule created from the JSON string.
        """
        data = json.loads(json_str)

        rruleset = dateutil.rrule.rruleset()
        rruleset._rrule = [
            dateutil.rrule.rrulestr(rrule) for rrule in data["rrule"]
        ]
        rruleset._rdate = [
            datetime.datetime.fromisoformat(rdate) for rdate in data["rdate"]
        ]
        rruleset._exrule = [
            dateutil.rrule.rrulestr(exrule) for exrule in data["exrule"]
        ]
        rruleset._exdate = [
            datetime.datetime.fromisoformat(exdate)
            for exdate in data["exdate"]
        ]
        return cls(rruleset, enabled=enabled)

    def to_json_str(self) -> str:
        """Convert the rruleset schedule to a JSON string.

        Returns
        -------
        str
            A JSON string representation of the schedule.

        Notes
        -----
        The JSON string contains the recurrence rules, dates, and exceptions
        in a format that can be parsed back into an ExecutionSchedule using
        the `from_json_str` method.
        """
        return json.dumps(
            {
                "rrule": [str(rrule) for rrule in self.rruleset._rrule],
                "rdate": [rdate.isoformat() for rdate in self.rruleset._rdate],
                "exrule": [str(exrule) for exrule in self.rruleset._exrule],
                "exdate": [
                    exdate.isoformat() for exdate in self.rruleset._exdate
                ],
            }
        )

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
