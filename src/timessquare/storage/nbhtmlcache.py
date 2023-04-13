"""The Redis-based cache of rendered HTML pages."""

from __future__ import annotations

from typing import Optional

from redis.asyncio import Redis

from timessquare.domain.nbhtml import NbHtmlModel

from .redisbase import RedisPageInstanceStore

__all__ = ["NbHtmlCacheStore"]


class NbHtmlCacheStore(RedisPageInstanceStore[NbHtmlModel]):
    """Manages the storage of HTML renderings of notebooks.

    The domain is `timessquare.domain.nbhtml.NbHtmlModel`.
    """

    def __init__(self, redis: Redis) -> None:
        super().__init__(
            redis=redis, key_prefix="nbhtml/", datatype=NbHtmlModel
        )

    async def store_nbhtml(
        self, nbhtml: NbHtmlModel, lifetime: Optional[int] = None
    ) -> None:
        """Store an HTML page.

        Parameters
        ----------
        nbhtml
            The HTML page domain model.
        lifetime
            The lifetime for the record in seconds. `None` to cache the record
            indefinitely.
        """
        key = nbhtml.create_key()
        await super().store_instance(key, nbhtml, lifetime=lifetime)
