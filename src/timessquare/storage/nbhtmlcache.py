"""The Redis-based cache of rendered HTML pages."""

from __future__ import annotations

from typing import Optional

import aioredis

from timessquare.domain.nbhtml import NbHtmlModel

from .redisbase import RedisStore


class NbHtmlCacheStore(RedisStore[NbHtmlModel]):
    """Manages the storage of HTML renderings of notebooks.

    The domain is `timessquare.domain.nbhtml.NbHtmlModel`.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        super().__init__(
            redis=redis, key_prefix="nbhtml", datatype=NbHtmlModel
        )

    async def store_nbhtml(
        self, nbhtml: NbHtmlModel, lifetime: Optional[int] = None
    ) -> None:
        """Store an HTML page.

        Parameters
        ----------
        nbhtml : `timessquare.domain.nbhtml.NbHtmlModel`
            The HTML page domain model.
        lifetime : int, optional
            The lifetime for the record in seconds. `None` to cache the record
            indefinitely.
        """
        key = nbhtml.create_key()
        await super().store(key, nbhtml, lifetime=lifetime)
