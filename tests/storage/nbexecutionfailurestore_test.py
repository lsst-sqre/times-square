"""Tests for the NbExecutionFailureStore."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from timessquare.config import config
from timessquare.domain.executionoutcome import (
    NotebookExecutionErrorCode,
    NotebookExecutionFailure,
)
from timessquare.domain.page import PageInstanceIdModel
from timessquare.storage.nbexecutionfailurestore import NbExecutionFailureStore


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[Redis]:
    """Return a Redis client for the test Redis instance."""
    client = Redis.from_url(str(config.redis_url))
    try:
        yield client
    finally:
        await client.aclose()


def _failure() -> NotebookExecutionFailure:
    return NotebookExecutionFailure(
        code=NotebookExecutionErrorCode.timeout,
        title="Notebook execution timeout",
        message="The notebook execution timed out.",
    )


@pytest.mark.asyncio
async def test_store_failure_uses_default_lifetime(redis: Redis) -> None:
    """A store constructed with a default lifetime applies that lifetime to
    the Redis TTL of a cached failure.
    """
    store = NbExecutionFailureStore(redis, default_lifetime=42)
    page_id = PageInstanceIdModel(
        name="default-lifetime", parameter_values={"a": "1"}
    )

    await store.store_failure(failure=_failure(), page_id=page_id)

    ttl = await redis.ttl(f"execution-failure/{page_id.cache_key}")
    assert 0 < ttl <= 42


@pytest.mark.asyncio
async def test_store_failure_lifetime_override(redis: Redis) -> None:
    """An explicit per-call lifetime overrides the store's default."""
    store = NbExecutionFailureStore(redis, default_lifetime=600)
    page_id = PageInstanceIdModel(
        name="override-lifetime", parameter_values={"a": "1"}
    )

    await store.store_failure(failure=_failure(), page_id=page_id, lifetime=17)

    ttl = await redis.ttl(f"execution-failure/{page_id.cache_key}")
    assert 0 < ttl <= 17
