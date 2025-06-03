"""Tests for the schedule domain."""

from __future__ import annotations

from dateutil.rrule import rruleset

from timessquare.domain.schedule import ExecutionSchedule

example_schedule = """
[
  {"freq": "weekly",
   "interval": 1,
   "by_weekday": [{"day": "monday", "index": null}]
  },
  {"freq": "monthly", "interval": 1, "by_month_day": [1]}
]
"""


def test_execution_schedule() -> None:
    """Test going from rruleset json to an rruleset via ExecutionSchedule."""
    schedule = ExecutionSchedule(rruleset_str=example_schedule, enabled=True)
    assert schedule.enabled is True
    assert schedule.schedule_rruleset == example_schedule

    rrule_set = schedule.rruleset
    assert isinstance(rrule_set, rruleset)
