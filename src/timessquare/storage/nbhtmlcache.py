"""The Redis-based cache of rendered HTML pages."""

from __future__ import annotations

from redis.asyncio import Redis

from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.page import PageIdModel

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
        self, nbhtml: NbHtmlModel, lifetime: int | None = None
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

    async def delete_objects_for_page(self, page_name: str) -> None:
        """Delete all cached renders for a page."""
        prefix = PageIdModel(name=page_name).cache_key_prefix
        await self.delete_all(f"{prefix}*")
