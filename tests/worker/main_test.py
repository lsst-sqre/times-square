"""Tests for the arq worker's configuration."""

from __future__ import annotations

from datetime import datetime, timedelta

from arq.cron import CronJob, next_cron

from timessquare.worker.main import WorkerSettings

EXPECTED_RUNS_PER_DAY = {
    "cron:schedule_runs": 288,  # every 5 minutes
    "cron:cleanup_scheduled_runs": 1,  # daily
    "cron:reconcile_github_names": 1,  # daily
}
"""How often each cron job is meant to fire in a 24 hour period."""


def _runs_in_a_day(job: CronJob) -> list[datetime]:
    """List the times a cron job fires over one full day."""
    start = datetime(2026, 1, 1, 0, 0, 0)  # noqa: DTZ001
    end = start + timedelta(days=1)
    runs: list[datetime] = []
    # next_cron only ever returns a time strictly after the one it is given,
    # so seed it a second before midnight to catch a firing at midnight.
    moment = start - timedelta(seconds=1)
    while True:
        moment = next_cron(
            moment,
            month=job.month,
            day=job.day,
            weekday=job.weekday,
            hour=job.hour,
            minute=job.minute,
            second=job.second,
            microsecond=job.microsecond,
        )
        if moment >= end:
            return runs
        runs.append(moment)


def test_cron_jobs_fire_at_their_intended_frequency() -> None:
    """Each cron job fires as often as its comment claims.

    arq treats an unset cron field as a wildcard rather than as zero, so a
    daily job declared with ``hour=11`` alone fires every minute from 11:00
    to 11:59 — sixty runs a day instead of one. Counting the firings over a
    whole day catches that class of mistake for every job at once.
    """
    jobs = {job.name: job for job in WorkerSettings.cron_jobs}
    assert set(jobs) == set(EXPECTED_RUNS_PER_DAY)
    counts = {name: len(_runs_in_a_day(job)) for name, job in jobs.items()}
    assert counts == EXPECTED_RUNS_PER_DAY


def test_daily_cron_jobs_run_at_the_top_of_their_hour() -> None:
    """The daily jobs fire once, at the start of the hour they name."""
    jobs = {job.name: job for job in WorkerSettings.cron_jobs}
    for name, hour in (
        ("cron:cleanup_scheduled_runs", 11),
        ("cron:reconcile_github_names", 12),
    ):
        runs = _runs_in_a_day(jobs[name])
        assert len(runs) == 1
        assert runs[0].hour == hour
        assert runs[0].minute == 0
