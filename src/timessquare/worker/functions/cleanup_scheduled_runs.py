"""Worker function that schedules runs for pages in the next time window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from safir.dependencies.db_session import db_session_dependency

from timessquare.factory import WorkerFactory


async def cleanup_scheduled_runs(
    ctx: dict[Any, Any],
) -> int:
    """Cleanup scheduled run records from the past."""
    logger = ctx["logger"].bind(
        task="cleanup_scheduled_runs",
    )

    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=ctx["process_context"],
        )
        scheduler_service = factory.create_run_scheduler_service()
        deleted_run_count = await scheduler_service.cleanup_old_runs(
            retention_period=timedelta(days=1),
        )

    return deleted_run_count
