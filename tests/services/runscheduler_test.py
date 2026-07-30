"""Tests for the RunSchedulerService's resilience to page schedules that
cannot be parsed or evaluated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
import structlog
from safir.arq import MockArqQueue
from structlog.testing import capture_logs

from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.domain.schedule import RunSchedule
from timessquare.services.runscheduler import RunSchedulerService
from timessquare.storage.page import PageStore
from timessquare.storage.scheduledrunstore import ScheduledRunStore

CHECK_WINDOW = timedelta(minutes=10)

BROKEN_RRULESET = json.dumps([{"freq": "fortnightly"}])
"""A stored rruleset that cannot be parsed into schedule rules."""


@pytest.fixture(autouse=True)
def _reset_schedule_warnings() -> Iterator[None]:
    """Clear the process-wide warn-once state around each test."""
    RunSchedulerService._warned_schedule_pages.clear()
    yield
    RunSchedulerService._warned_schedule_pages.clear()


def _rruleset_for_date(when: datetime) -> str:
    """Build an rruleset JSON string with a single run at ``when``."""
    return json.dumps([{"date": when.isoformat()}])


def _make_page(name: str, rruleset: str) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title=name,
        date_added=datetime.now(tz=UTC),
        schedule_rruleset=rruleset,
        schedule_enabled=True,
    )


def _make_service(pages: list[PageModel]) -> RunSchedulerService:
    page_store = AsyncMock(spec=PageStore)
    page_store.list_scheduled_pages.return_value = pages
    scheduled_run_store = AsyncMock(spec=ScheduledRunStore)
    scheduled_run_store.check_existing_run.return_value = None
    return RunSchedulerService(
        scheduled_run_store=scheduled_run_store,
        page_store=page_store,
        arq_queue=MockArqQueue(),
        logger=structlog.get_logger("timessquare"),
    )


def _warnings(
    logs: Sequence[MutableMapping[str, Any]],
) -> list[MutableMapping[str, Any]]:
    return [entry for entry in logs if entry["log_level"] == "warning"]


def _errors(
    logs: Sequence[MutableMapping[str, Any]],
) -> list[MutableMapping[str, Any]]:
    return [
        entry
        for entry in logs
        if entry["log_level"] in {"error", "critical", "exception"}
    ]


@pytest.mark.asyncio
async def test_healthy_pages_scheduled_around_broken_page() -> None:
    """A page with an unparsable schedule is skipped, but its healthy
    neighbours are still scheduled.
    """
    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    pages = [
        _make_page(
            "healthy-a", _rruleset_for_date(now + timedelta(minutes=5))
        ),
        _make_page("broken", BROKEN_RRULESET),
        _make_page(
            "healthy-b", _rruleset_for_date(now + timedelta(minutes=6))
        ),
    ]
    service = _make_service(pages)

    with capture_logs() as logs:
        runs = await service.schedule_due_runs(check_window=CHECK_WINDOW)

    assert [run.page_name for run in runs] == ["healthy-a", "healthy-b"]
    assert _errors(logs) == []
    warnings = _warnings(logs)
    assert len(warnings) == 1
    assert warnings[0]["page_name"] == "broken"


@pytest.mark.asyncio
async def test_broken_schedule_warns_once_per_process() -> None:
    """Repeated ticks do not re-log a warning for the same page, even with a
    freshly-constructed service each tick.
    """
    pages = [_make_page("broken", BROKEN_RRULESET)]

    with capture_logs() as logs:
        for _ in range(3):
            service = _make_service(pages)
            runs = await service.schedule_due_runs(check_window=CHECK_WINDOW)
            assert runs == []

    assert _errors(logs) == []
    assert len(_warnings(logs)) == 1


@pytest.mark.asyncio
async def test_unevaluatable_schedule_warns_not_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schedule that parses but explodes during evaluation (the DM-55467
    incident) is a warning, not an error.
    """

    def _raise(self: RunSchedule, after: datetime | None) -> None:
        raise AttributeError("'NoneType' object has no attribute 'tzinfo'")

    monkeypatch.setattr(RunSchedule, "next", _raise)

    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    pages = [_make_page("broken", _rruleset_for_date(now))]
    service = _make_service(pages)

    with capture_logs() as logs:
        runs = await service.schedule_due_runs(check_window=CHECK_WINDOW)

    assert runs == []
    assert _errors(logs) == []
    warnings = _warnings(logs)
    assert len(warnings) == 1
    assert warnings[0]["page_name"] == "broken"
    assert "tzinfo" in warnings[0]["reason"]


@pytest.mark.asyncio
async def test_warning_rearms_when_schedule_heals() -> None:
    """A page that is fixed and then breaks again warns a second time."""
    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    broken = _make_page("flaky", BROKEN_RRULESET)
    healthy = _make_page(
        "flaky", _rruleset_for_date(now + timedelta(minutes=5))
    )

    with capture_logs() as logs:
        for pages in ([broken], [healthy], [broken]):
            service = _make_service(pages)
            await service.schedule_due_runs(check_window=CHECK_WINDOW)

    assert _errors(logs) == []
    warnings = _warnings(logs)
    assert len(warnings) == 2
    assert [warning["page_name"] for warning in warnings] == [
        "flaky",
        "flaky",
    ]


@pytest.mark.asyncio
async def test_warning_reason_names_the_exception_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning's reason includes the exception class, which is the only
    diagnostic for failures whose message is uninformative on its own.
    """

    def _raise(self: RunSchedule, after: datetime | None) -> None:
        raise KeyError("freq")

    monkeypatch.setattr(RunSchedule, "next", _raise)

    now = datetime.now(tz=UTC).replace(second=0, microsecond=0)
    pages = [_make_page("broken", _rruleset_for_date(now))]
    service = _make_service(pages)

    with capture_logs() as logs:
        await service.schedule_due_runs(check_window=CHECK_WINDOW)

    warnings = _warnings(logs)
    assert len(warnings) == 1
    assert warnings[0]["reason"] == "KeyError: 'freq'"
