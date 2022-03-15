"""The Redis-based cache of rendered HTML pages."""

from __future__ import annotations

from typing import Any, AsyncIterable, Mapping, Optional

import aioredis

from timessquare.domain.nbhtml import NbHtmlModel

from .redisbase import RedisStore


class NbHtmlCacheStore:
    """Manages the storage of HTML renderings of notebooks.

    The domain is `timessquare.domain.nbhtml.NbHtmlModel`.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = RedisStore[NbHtmlModel](
            redis=redis, key_prefix="nbhtml", datatype=NbHtmlModel
        )

    async def store(
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
        key = self._redis.calculate_redis_key(
            page_name=nbhtml.page_name, parameters=nbhtml.parameters
        )
        await self._redis.store(key, nbhtml, lifetime=lifetime)

    async def get(
        self, *, page_name: str, parameters: Mapping[str, Any]
    ) -> Optional[NbHtmlModel]:
        """Get the NbHtmlModel of a page for a given set of parameters.

        Parameters
        ----------
        page_name : str
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).
        parameters : dict
            The parameter values, keyed by the parameter names, with values as
            cast Python types
            (`timessquare.domain.page.PageParameterSchema.cast_value`).

        Returns
        -------
        nbhtml : `timessquare.domain.nbhtml.NbHtmlModel`
            The HTML page domain model.
        """
        key = self._redis.calculate_redis_key(
            page_name=page_name, parameters=parameters
        )
        return await self._redis.get(key)

    async def iter_keys_for_page(self, page_name: str) -> AsyncIterable[str]:
        """Iterate over all keys for a page.

        Parameters
        ----------
        page_name : str
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).

        Yields
        ------
        key : str
            Yields keys for a page.
        """
        async for key in self._redis.iter_keys_for_page(page_name):
            yield key

    async def delete(
        self, *, page_name: str, parameters: Mapping[str, Any]
    ) -> bool:
        """Delete the NbHtmlModel of a page for a given set of parameters,
        if available.

        Parameters
        ----------
        page_name : str
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).
        parameters : dict
            The parameter values, keyed by the parameter names, with values as
            cast Python types
            (`timessquare.domain.page.PageParameterSchema.cast_value`).

        Returns
        -------
        deleted : bool
            `True` if a record was deleted, `False` otherwise.
        """
        key = self._redis.calculate_redis_key(
            page_name=page_name, parameters=parameters
        )
        return await self._redis.delete(key)
