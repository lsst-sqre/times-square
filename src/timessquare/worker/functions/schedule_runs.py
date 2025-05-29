"""Worker function that schedules runs for pages in the next time window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from safir.dependencies.db_session import db_session_dependency

from timessquare.services.runscheduler import RunSchedulerService
from timessquare.storage.page import PageStore
from timessquare.storage.scheduledrunstore import ScheduledRunStore
from timessquare.worker.servicefactory import create_arq_queue


async def schedule_runs(
    ctx: dict[Any, Any],
) -> int:
    """Schedule runs for pages within the next time window."""
    logger = ctx["logger"].bind(
        task="schedule_runs",
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
        scheduled_runs = await scheduler_service.schedule_due_executions(
            # coordinate with periodicity of this job in worker
            check_window=timedelta(minutes=10),
        )
        await db_session.commit()
        logger.info(
            "Scheduled runs completed",
            count=len(scheduled_runs),
        )

    return len(scheduled_runs)
