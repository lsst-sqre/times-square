"""Test the schema of the database."""

import subprocess

import pytest
from safir.database import create_database_engine, drop_database

from timessquare.config import config
from timessquare.dbschema import Base


@pytest.mark.asyncio
async def test_schema() -> None:
    """Ensure that the SQLAlchemy model is consistent with the current
    Alembic revision.
    """
    engine = create_database_engine(
        config.database_url, config.database_password
    )
    await drop_database(engine, Base.metadata)
    await engine.dispose()
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["alembic", "check"], check=True)
