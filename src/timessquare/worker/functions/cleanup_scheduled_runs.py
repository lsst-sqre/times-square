"""Worker function that schedules runs for pages in the next time window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from safir.dependencies.db_session import db_session_dependency

from timessquare.services.runscheduler import RunSchedulerService
from timessquare.storage.page import PageStore
from timessquare.storage.scheduledrunstore import ScheduledRunStore
from timessquare.worker.servicefactory import create_arq_queue


async def cleanup_scheduled_runs(
    ctx: dict[Any, Any],
) -> int:
    """Cleanup scheduled run records from the past."""
    logger = ctx["logger"].bind(
        task="cleanup_scheduled_runs",
    )

    async for db_session in db_session_dependency():
        arq_queue = await create_arq_queue()
        page_store = PageStore(db_session)
        scheduled_run_store = ScheduledRunStore(db_session)

        scheduler_service = RunSchedulerService(
            scheduled_run_store=scheduled_run_store,
            page_store=page_store,
            arq_queue=arq_queue,
            logger=logger,
        )
        deleted_run_count = await scheduler_service.cleanup_old_runs(
            retention_period=timedelta(days=1),
        )

    return deleted_run_count
