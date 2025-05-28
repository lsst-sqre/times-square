"""Storage interface for scheduled runs in the database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_scoped_session

from timessquare.dbschema.scheduledrun import SqlScheduledRun
from timessquare.domain.scheduledrun import ScheduledRun

__all__ = ["ScheduledRunStore"]


class ScheduledRunStore:
    """A storage interface for schedled runs in the database.

    Parameters
    ----------
    session
        The SQLAlchemy database session.
    """

    def __init__(self, session: async_scoped_session) -> None:
        """Initialize the store with a database session."""
        self._session = session

    async def add(self, scheduled_run: ScheduledRun) -> None:
        """Add a scheduled run to the database.

        Parameters
        ----------
        scheduled_run
            The scheduled run to add.
        """
        sql_scheduled_run = SqlScheduledRun(
            page_name=scheduled_run.page_name,
            scheduled_time=scheduled_run.scheduled_time,
            created_at=scheduled_run.created_at,
            job_id=scheduled_run.job_id,
        )
        self._session.add(sql_scheduled_run)
        await self._session.flush()

    async def check_existing_run(
        self, page_name: str, scheduled_time: datetime
    ) -> bool:
        """Check if a scheduled run already exists for the given page and time.

        Parameters
        ----------
        page_name
            The name of the page.
        scheduled_time
            The time when the page is scheduled to be run.

        Returns
        -------
        bool
            True if a scheduled run exists for the given page and time, False
            otherwise.
        """
        stmt = select(SqlScheduledRun).where(
            SqlScheduledRun.page_name == page_name,
            SqlScheduledRun.scheduled_time == scheduled_time,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def delete(self, scheduled_run: ScheduledRun) -> None:
        """Delete a scheduled run from the database.

        Parameters
        ----------
        scheduled_run
            The scheduled run to delete.
        """
        stmt = select(SqlScheduledRun).where(
            SqlScheduledRun.page_name == scheduled_run.page_name,
            SqlScheduledRun.scheduled_time == scheduled_run.scheduled_time,
        )
        result = await self._session.execute(stmt)
        sql_scheduled_run = result.scalar_one_or_none()
        if sql_scheduled_run:
            await self._session.delete(sql_scheduled_run)
            await self._session.flush()
