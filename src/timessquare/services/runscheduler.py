"""Service for managing schedule runs of pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from safir.arq import ArqQueue
from structlog.stdlib import BoundLogger

from timessquare.domain.page import PageModel
from timessquare.domain.scheduledrun import ScheduledRun
from timessquare.exceptions import ScheduleEvaluationError
from timessquare.storage.page import PageStore
from timessquare.storage.scheduledrunstore import ScheduledRunStore

__all__ = ["RunSchedulerService"]

SCHEDULE_EVALUATION_ERRORS = (ValueError, TypeError, AttributeError, KeyError)
"""Exceptions from parsing or evaluating a stored rruleset that are treated
as per-page configuration errors.

`pydantic.ValidationError` is a `ValueError` subclass, so this covers both
unparsable rrulesets and rrulesets that fail while dateutil computes the next
occurrence.
"""


class RunSchedulerService:
    """Service for managing schedule runs of pages.

    Parameters
    ----------
    store
        The storage interface for scheduled runs.
    """

    _warned_schedule_pages: ClassVar[set[str]] = set()
    """Names of pages already warned about for an un-evaluatable schedule.

    This state is shared by every service instance in the process so that the
    scheduler warns only once per page, rather than on every scheduling tick.
    A page is dropped from this set once its schedule evaluates successfully
    again, so a later breakage is warned about afresh. It is deliberately not
    persisted; resetting on restart is acceptable.
    """

    def __init__(
        self,
        *,
        scheduled_run_store: ScheduledRunStore,
        page_store: PageStore,
        arq_queue: ArqQueue,
        logger: BoundLogger,
    ) -> None:
        """Initialize the service with a storage interface.

        Parameters
        ----------
        scheduled_run_store
            The storage interface for scheduled runs.
        page_store
            The database store for pages.
        arq_queue
            The Arq queue for scheduling background tasks.
        logger
            The logger for the service.
        """
        self._scheduled_run_store = scheduled_run_store
        self._page_store = page_store
        self._arq_queue = arq_queue
        self._logger = logger

    async def schedule_due_runs(
        self, check_window: timedelta
    ) -> list[ScheduledRun]:
        """Check for and schedule any due page executions.

        Parameters
        ----------
        check_window
            How far into the future to check for due executions.

        Returns
        -------
        list
            The list of newly scheduled runs.
        """
        now = datetime.now(tz=UTC)

        # Get all pages with scheduling enabled
        pages = await self._page_store.list_scheduled_pages()

        new_scheduled_runs: list[ScheduledRun] = []
        for page in pages:
            try:
                scheduled_run = await self._schedule_due_for_page(
                    page=page,
                    now=now,
                    check_window=check_window,
                )
                if scheduled_run is not None:
                    new_scheduled_runs.append(scheduled_run)
            except ScheduleEvaluationError as e:
                self._warn_unevaluatable_schedule(page, e)
            except Exception:
                self._logger.exception(
                    "Failed to schedule page execution",
                    page_name=page.name,
                    rrule=page.schedule_rruleset,
                )

        return new_scheduled_runs

    def _warn_unevaluatable_schedule(
        self, page: PageModel, error: ScheduleEvaluationError
    ) -> None:
        """Warn once per process about a page whose schedule can't be used.

        A page with a broken stored rruleset fails on every scheduling tick,
        so this is logged at warning level, and only the first time the page
        is seen, instead of as a per-tick error.
        """
        if page.name in self._warned_schedule_pages:
            return
        self._warned_schedule_pages.add(page.name)
        self._logger.warning(
            "Skipping page with an un-evaluatable run schedule",
            page_name=page.name,
            reason=error.reason,
            schedule_rruleset=page.schedule_rruleset,
        )

    def _compute_next_run(
        self, *, page: PageModel, now: datetime
    ) -> datetime | None:
        """Compute a page's next scheduled run time.

        Raises
        ------
        ScheduleEvaluationError
            Raised if the page's stored rruleset cannot be parsed or
            evaluated.
        """
        try:
            schedule = page.schedule
            if schedule is None:
                self._logger.warning(
                    "Page has no run schedule, despite being expected to",
                    page_name=page.name,
                )
                next_run = None
            else:
                next_run = schedule.next(after=now)
        except SCHEDULE_EVALUATION_ERRORS as e:
            reason = f"{type(e).__name__}: {e}"
            raise ScheduleEvaluationError(page.name, reason) from e
        # The page's schedule is usable, so re-arm its warning: if the
        # schedule breaks again later, that breakage is logged rather than
        # silently deduplicated against the earlier one.
        self._warned_schedule_pages.discard(page.name)
        return next_run

    async def _schedule_due_for_page(
        self, *, page: PageModel, now: datetime, check_window: timedelta
    ) -> ScheduledRun | None:
        next_run = self._compute_next_run(page=page, now=now)
        self._logger.debug(
            "Computed scheduled run for page",
            page_name=page.name,
            next_run=next_run.isoformat() if next_run else None,
        )

        if next_run and (next_run - now) <= check_window:
            # Check if there's an existing scheduled run
            existing_run = await self._scheduled_run_store.check_existing_run(
                page_name=page.name, scheduled_time=next_run
            )
            if existing_run:
                self._logger.debug(
                    "Scheduled run already exists",
                    page_name=page.name,
                    scheduled_time=next_run,
                )
                return None

            # Schedule the execution
            job_metadata = await self._arq_queue.enqueue(
                "scheduled_page_run",
                page_name=page.name,
                scheduled_time=next_run,
                _defer_until=next_run,
            )
            scheduled_run = ScheduledRun(
                page_name=page.name,
                scheduled_time=next_run,
                created_at=now,
                job_id=job_metadata.id,
            )
            await self._scheduled_run_store.add(scheduled_run)

            self._logger.info(
                "Scheduled page execution",
                page_name=page.name,
                next_execution=next_run,
            )
            return scheduled_run

        return None

    async def cleanup_old_runs(self, retention_period: timedelta) -> int:
        """Clean up old scheduled runs that are beyond the retention period.

        Parameters
        ----------
        retention_period
            The duration for which scheduled runs should be retained.

        Returns
        -------
        int
            The number of old runs deleted.
        """
        now = datetime.now(tz=UTC)
        cutoff_time = now - retention_period

        deleted_count = await self._scheduled_run_store.delete_old_runs(
            cutoff_time
        )
        self._logger.info(
            "Cleaned up old scheduled runs",
            deleted_count=deleted_count,
            retention_period=retention_period,
            cutoff_time=cutoff_time.isoformat(),
        )
        return deleted_count
