""""Base functionality for redis storage."""

from __future__ import annotations

from typing import AsyncIterable, Generic, Optional, Type, TypeVar

import aioredis
from pydantic import BaseModel

from timessquare.domain.page import PageInstanceIdModel

T = TypeVar("T", bound="BaseModel")


class RedisStore(Generic[T]):
    """A base class for Redis-based storage of Pydantic models as JSON.

    Parameters
    ----------
    redis : `aioredis.Redis`
        The Redis client.
    key_prefix : `str`
        The prefix for any data stored in Redis.
    datatype : `pydantic.BaseModel` - type
        The pydantic class of object stored through this RedisStore.
    """

    def __init__(
        self,
        *,
        redis: aioredis.Redis,
        key_prefix: str,
        datatype: Type[T],
    ) -> None:
        self._redis = redis
        self._key_prefix = key_prefix
        self._datatype = datatype

    def calculate_redis_key(self, page_id: PageInstanceIdModel) -> str:
        """Create the redis key for given the page's name and
        parameter values with a datastore's redis key prefix.

        Parameters
        ----------
        page_id : `timessquare.domain.page.PageInstanceIdModel`
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.

        Returns
        -------
        key : `str`
            The unique redis key for this combination of page name and
            parameter values for a given datastore.
        """
        return f"{self._key_prefix}/{page_id.cache_key}"

    async def store(
        self,
        page_id: PageInstanceIdModel,
        data: T,
        lifetime: Optional[int] = None,
    ) -> None:
        """Store a pydantic object to Redis.

        The data is persisted in Redis as a JSON string.

        Parameters
        ----------
        page_id : `timessquare.domain.page.PageInstanceIdModel`
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.
        data : `pydantic.BaseModel`
            A pydantic model of the type this RedisStore instance is
            instantiated for.
        lifetime : int, optional
            The lifetime (in seconds) of the persisted data in Redis. If
            `None`, the data is persisted forever.
        """
        key = self.calculate_redis_key(page_id)
        serialized_data = data.json()
        await self._redis.set(key, serialized_data, ex=lifetime)

    async def get(self, page_id: PageInstanceIdModel) -> Optional[T]:
        """Get the data stored for a page instance, deserializing it into the
        Pydantic model type.

        Parameters
        ----------
        page_id : `timessquare.domain.page.PageInstanceIdModel`
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.

        Returns
        -------
        data : `pydantic.BaseModel`, optional
            The dataset, as a Pydantic model. If the dataset is not found at
            the key, `None` is returned.
        """
        key = self.calculate_redis_key(page_id)
        serialized_data = await self._redis.get(key)
        if not serialized_data:
            return None

        return self._datatype.parse_raw(serialized_data.decode())

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
        pattern = f"{self._key_prefix}/{page_name}/*"
        async for key in self._redis.scan_iter(pattern):
            yield key

    async def delete(self, page_id: PageInstanceIdModel) -> bool:
        """Delete a dataset for a specific page instance.

        Parameters
        ----------
        key : `str`
            The key where the data is stored.

        Returns
        -------
        deleted : bool
            `True` if a record was deleted, `False` otherwise.
        """
        key = self.calculate_redis_key(page_id)
        count = await self._redis.delete(key)
        return count > 0

    async def delete_all(self) -> int:
        """Delete all records with the store's key prefix.

        Returns
        -------
        count : `int`
            The number of records deleted.
        """
        pattern = f"{self._key_prefix}/*"
        count = 0
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)
            count += 1
        return count > 0
