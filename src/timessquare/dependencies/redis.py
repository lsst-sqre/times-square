"""Redis dependency for FastAPI."""

from redis.asyncio import BlockingConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

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
        self, redis_url: str, password: str | None = None
    ) -> None:
        redis_pool = BlockingConnectionPool.from_url(
            str(redis_url),
            password=password,
            max_connections=25,
            retry=Retry(
                ExponentialBackoff(base=0.2, cap=1.0),
                10,
            ),
            retry_on_timeout=True,
            socket_keepalive=True,
            socket_timeout=5,
            timeout=30,
        )
        self.redis = Redis.from_pool(redis_pool)

    async def __call__(self) -> Redis:
        """Return the redis pool."""
        if self.redis is None:
            raise RuntimeError("RedisDependency is not initialized")
        return self.redis

    async def close(self) -> None:
        """Close the open Redis pool.

        Should be called from a shutdown hook to ensure that the Redis clients
        are cleanly shut down and any pending writes are complete.
        """
        if self.redis:
            await self.redis.aclose()
            self.redis = None


redis_dependency = RedisDependency()
"""The dependency that will return the Redis pool."""
