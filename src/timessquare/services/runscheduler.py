"""Service for managing schedule runs of pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from safir.arq import ArqQueue
from structlog.stdlib import BoundLogger

from timessquare.domain.page import PageModel
from timessquare.domain.scheduledrun import ScheduledRun
from timessquare.storage.page import PageStore
from timessquare.storage.scheduledrunstore import ScheduledRunStore

__all__ = ["RunSchedulerService"]


class RunSchedulerService:
    """Service for managing schedule runs of pages.

    Parameters
    ----------
    store
        The storage interface for scheduled runs.
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

    async def schedule_due_executions(
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
            except Exception:
                self._logger.exception(
                    "Failed to schedule page execution",
                    page_name=page.name,
                    rrule=page.schedule_rruleset,
                )

        return new_scheduled_runs

    async def _schedule_due_for_page(
        self, *, page: PageModel, now: datetime, check_window: timedelta
    ) -> ScheduledRun | None:
        try:
            schedule = page.execution_schedule
        except ValidationError:
            self._logger.exception(
                "Invalid execution schedule for page",
                page_name=page.name,
                schedule_rruleset=page.schedule_rruleset,
            )
        if schedule is None:
            self._logger.warning(
                "Page has no execution schedule, despite being expoected to",
                page_name=page.name,
            )
            return None

        next_execution = schedule.next(after=now)

        if next_execution and (next_execution - now) <= check_window:
            # Check if there's an existing scheduled run
            existing_run = await self._scheduled_run_store.check_existing_run(
                page_name=page.name, scheduled_time=next_execution
            )
            if existing_run:
                self._logger.debug(
                    "Scheduled run already exists",
                    page_name=page.name,
                    scheduled_time=next_execution,
                )
                return None

            # Schedule the execution
            job_metadata = await self._arq_queue.enqueue(
                "scheduled_page_run",
                page_name=page.name,
                scheduled_time=next_execution,
                _defer_until=next_execution,
            )
            scheduled_run = ScheduledRun(
                page_name=page.name,
                scheduled_time=next_execution,
                created_at=now,
                job_id=job_metadata.id,
            )
            await self._scheduled_run_store.add(scheduled_run)

            self._logger.info(
                "Scheduled page execution",
                page_name=page.name,
                next_execution=next_execution,
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
