"""Redis dependency for FastAPI."""

from typing import Optional

from redis.asyncio import Redis

__all__ = ["RedisDependency", "redis_dependency"]


class RedisDependency:
    """Provides an asyncio-based Redis client as a dependency.

    Notes
    -----
    This dependency must be initialized in a start-up hook (`initialize`) and
    closed in a shut down hook (`close`).
    """

    def __init__(self) -> None:
        self.redis: Redis | None = None

    async def initialize(
        self, redis_url: str, password: Optional[str] = None
    ) -> None:
        self.redis = Redis.from_url(redis_url, password=password)

    async def __call__(self) -> Redis:
        """Returns the redis pool."""
        if self.redis is None:
            raise RuntimeError("RedisDependency is not initialized")
        return self.redis

    async def close(self) -> None:
        """Close the open Redis pool.

        Should be called from a shutdown hook to ensure that the Redis clients
        are cleanly shut down and any pending writes are complete.
        """
        if self.redis:
            await self.redis.close()
            await self.redis.connection_pool.disconnect()
            self.redis = None


redis_dependency = RedisDependency()
"""The dependency that will return the Redis pool."""
