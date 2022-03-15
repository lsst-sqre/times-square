""""Base functionality for redis storage."""

from __future__ import annotations

import json
from base64 import b64encode
from typing import (
    Any,
    AsyncIterable,
    Generic,
    Mapping,
    Optional,
    Type,
    TypeVar,
)

import aioredis
from pydantic import BaseModel

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

    def calculate_redis_key(
        self, *, page_name: str, parameters: Mapping[str, Any]
    ) -> str:
        """Create the redis key for given the page's name and
        parameter values with a datastore's redis key prefix.

        Parameters
        ----------
        page_name : `str`
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).
        parameters : `dict`
            The parameter values, keyed by the parameter names, with values as
            cast Python types
            (`timessquare.domain.page.PageParameterSchema.cast_value`).

        Returns
        -------
        key : `str`
            The unique redis key for this combination of page name and
            parameter values for a given datastore.
        """
        encoded_parameters_key = b64encode(
            json.dumps(
                {k: p for k, p in parameters.items()}, sort_keys=True
            ).encode("utf-8")
        ).decode("utf-8")
        return f"{self._key_prefix}/{page_name}/{encoded_parameters_key}"

    async def store(
        self, key: str, data: T, lifetime: Optional[int] = None
    ) -> None:
        """Store a pydantic object to redis at a given key.

        The data is persisted in redis as a JSON string.

        Parameters
        ----------
        key : `str`
            The key where the data is stored.
        data : `pydantic.BaseModel`
            A pydantic model of the type this RedisStore instance is
            instantiated for.
        lifetime : int, optional
            The lifetime (in seconds) of the persisted data in Redis. If
            `None`, the data is persisted forever.
        """
        serialized_data = data.json()
        await self._redis.set(key, serialized_data, ex=lifetime)

    async def get(self, key: str) -> Optional[T]:
        """Get the data stored at a Redis key, deserializing it into the
        Pydantic model type.

        Parameters
        ----------
        key : `str`
            The key where the data is stored.

        Returns
        -------
        data : `pydantic.BaseModel`, optional
            The dataset, as a Pydantic model. If the dataset is not found at
            the key, `None` is returned.
        """
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
        pattern = r"^{self._key_prefix}\/{page_name}\/"
        async for key in self._redis.scan_iter(pattern):
            yield key

    async def delete(self, key: str) -> bool:
        """Delete a dataset at a specific key.

        Parameters
        ----------
        key : `str`
            The key where the data is stored.

        Returns
        -------
        deleted : bool
            `True` if a record was deleted, `False` otherwise.
        """
        count = await self._redis.delete(key)
        return count > 0
