"""A proof-of-concept worker function."""

from __future__ import annotations

from typing import Any, Dict


async def ping(ctx: Dict[Any, Any]) -> str:
    logger = ctx["logger"].bind(task="ping")
    logger.info("Running ping")
    return "pong"
