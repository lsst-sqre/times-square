"""Test fixtures for times-square tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
import structlog
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from gidgethub.httpx import GitHubAPI
from httpx import ASGITransport, AsyncClient
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)

from timessquare import main
from timessquare.config import config
from timessquare.dbschema import Base


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    logger = structlog.get_logger(config.logger_name)

    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    await engine.dispose()
    async with LifespanManager(main.app):
        yield main.app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    base = "https://example.com/"
    headers = {"X-Auth-Request-User": "testuser"}
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url=base, headers=headers
    ) as client:
        yield client


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient``."""
    async with AsyncClient() as client:
        yield client


@pytest_asyncio.fixture
async def github_client() -> AsyncIterator[GitHubAPI]:
    """Return a HTTPX GitHub API client."""
    async with AsyncClient() as client:
        yield GitHubAPI(client, "lsst-sqre/times-square")
