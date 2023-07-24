"""A proof-of-concept worker function."""

from __future__ import annotations

from typing import Any


async def ping(ctx: dict[Any, Any]) -> str:
    """Process ping queue tasks."""
    logger = ctx["logger"].bind(task="ping")
    logger.info("Running ping")
    return "pong"
