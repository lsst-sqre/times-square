"""The Redis-based cache of rendered HTML pages."""

from __future__ import annotations

from typing import Any, AsyncIterable, Mapping, Optional

import aioredis

from timessquare.domain.nbhtml import NbHtmlModel

from .redisutils import calculate_key


class NbHtmlCacheStore:
    """Manages the storage of HTML renderings of notebooks.

    The domain is `timessquare.domain.nbhtml.NbHtmlModel`.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def store(
        self, nbhtml: NbHtmlModel, lifetime: Optional[int] = None
    ) -> None:
        """Store an HTML page.

        Parameters
        ----------
        nbhtml : `timessquare.domain.nbhtml.NbHtmlModel`
            The HTML page domain model.
        lifetime : int, optional
            The lifetime for the record. `None` to cache the record
            indefinitely.
        """
        key = NbHtmlCacheStore.calculate_key(
            page_name=nbhtml.page_name, parameters=nbhtml.parameters
        )
        serialized_data = nbhtml.json()
        await self._redis.set(key, serialized_data, ex=lifetime)

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
        key = NbHtmlCacheStore.calculate_key(
            page_name=page_name, parameters=parameters
        )
        serialized_data = await self._redis.get(key)
        if not serialized_data:
            return None

        return NbHtmlModel.parse_raw(serialized_data.decode())

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
        pattern = r"^{page_name}\/"
        async for key in self._redis.scan_iter(pattern):
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

        Return
        ------
        deleted : bool
            `True` if a record was deleted, `False` otherwise.
        """
        key = NbHtmlCacheStore.calculate_key(
            page_name=page_name, parameters=parameters
        )
        count = await self._redis.delete(key)
        return count > 0

    @staticmethod
    def calculate_key(*, page_name: str, parameters: Mapping[str, Any]) -> str:
        """Create the redis key for an NbHtmlModel given the page's name and
        parameter values.

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
        key : str
            The unique redis key for this combination of page name and
            parameter values.
        """
        return calculate_key(
            prefix="nbhtml", page_name=page_name, parameters=parameters
        )
