"""Tests for the process context and factory."""

from __future__ import annotations

import pytest
from httpx import Timeout

from timessquare.config import config
from timessquare.factory import ProcessContext


def test_http_client_timeout_default() -> None:
    """The HTTP client timeout config defaults to 30 seconds."""
    assert config.http_client_timeout == 30


@pytest.mark.asyncio
async def test_process_context_http_client_timeout() -> None:
    """ProcessContext.create() builds the shared client with the configured
    timeout.
    """
    process_context = await ProcessContext.create()
    try:
        assert process_context.http_client.timeout == Timeout(
            config.http_client_timeout
        )
    finally:
        await process_context.aclose()
