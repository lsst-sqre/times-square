"""Utility functions for database management.

SQLAlchemy, when creating a database schema, can only know about the tables
that have been registered via a metaclass.  This module therefore must import
every schema to ensure that SQLAlchemy has a complete view.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from . import dbschema  # ensures all schemas are imported
from .dbschema import SqlPage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine
    from structlog.stdlib import BoundLogger

    from timessquare.config import Config

__all__ = ["check_database", "initialize_database"]


async def drop_schema(engine: AsyncEngine) -> None:
    """Drop all tables to reset the database."""
    async with engine.begin() as conn:
        await conn.run_sync(dbschema.Base.metadata.drop_all)


async def initialize_schema(engine: AsyncEngine) -> None:
    """Initialize the database with all schema."""
    async with engine.begin() as conn:
        await conn.run_sync(dbschema.Base.metadata.create_all)


def _create_session_factory(engine: AsyncEngine) -> sessionmaker:
    """Create a session factory that generates async sessions."""
    return sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def check_database(url: str, logger: BoundLogger) -> None:
    """Check that the database is accessible.

    Parameters
    ----------
    config : `gafaelfawr.config.Config`
        The Gafaelfawr configuration.
    logger : `structlog.stdlib.BoundLogger`
        Logger used to report problems
    """
    engine = create_async_engine(url, future=True)
    factory = _create_session_factory(engine)
    for _ in range(5):
        try:
            async with factory() as session:
                async with session.begin():
                    await session.execute(select(SqlPage).limit(1))
                    return
        except (ConnectionRefusedError, OperationalError):
            logger.info("database not ready, waiting two seconds")
            time.sleep(2)
            continue

    # If we got here, we failed five times.  Try one last time without
    # catching exceptions so that we raise the appropriate exception to our
    # caller.
    async with factory() as session:
        async with session.begin():
            await session.execute(select(SqlPage).limit(1))


async def initialize_database(config: Config, reset: bool = False) -> None:
    """Create and initialize a new database.

    Parameters
    ----------
    config : `timessquare.config.Config`
        The application configuration.
    reset : `bool`
        If set to `True`, drop all tables and reprovision the database.
        Useful when running tests with an external database.  Default is
        `False`.
    """
    logger = structlog.get_logger(config.logger_name)

    # Check connectivity to the database and retry if needed.  This uses a
    # pre-ping to ensure the database is available and attempts to connect
    # five times with a two second delay between each attempt.
    success = False
    engine = create_async_engine(config.asyncpg_database_url, future=True)
    for _ in range(5):
        try:
            if reset:
                await drop_schema(engine)
            await initialize_schema(engine)
            success = True
        except (ConnectionRefusedError, OperationalError):
            logger.info("database not ready, waiting two seconds")
            time.sleep(2)
            continue
        if success:
            logger.info("initialized database schema")
            break
    if not success:
        msg = "database schema initialization failed (database not reachable?)"
        logger.error(msg)
        await engine.dispose()
        return

    # Add any initial data here.

    await engine.dispose()
