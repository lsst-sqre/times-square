"""Worker function that schedules runs for pages in the next time window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from safir.dependencies.db_session import db_session_dependency

from timessquare.factory import WorkerFactory


async def schedule_runs(
    ctx: dict[Any, Any],
) -> int:
    """Schedule runs for pages within the next time window."""
    logger = ctx["logger"].bind(
        task="schedule_runs",
    )

    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=ctx["process_context"],
        )
        scheduler_service = factory.create_run_scheduler_service()
        scheduled_runs = await scheduler_service.schedule_due_runs(
            # coordinate with periodicity of this job in worker
            check_window=timedelta(minutes=10),
        )
        await db_session.commit()
        logger.info(
            "Scheduled runs completed",
            count=len(scheduled_runs),
        )

    return len(scheduled_runs)
