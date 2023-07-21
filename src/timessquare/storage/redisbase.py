""""Base for Redis page instance cache storage."""

from __future__ import annotations

from collections.abc import AsyncIterable

from safir.redis import PydanticRedisStorage, S

from timessquare.domain.page import PageInstanceIdModel

__all__ = ["RedisPageInstanceStore"]


class RedisPageInstanceStore(PydanticRedisStorage[S]):
    """A base class for Redis-based storage of page-instance-related Pydantic
    models as JSON.

    Parameters
    ----------
    datatype
        The class of Pydantic model to store.
    redis
        The Redis client.
    key_prefix
        The prefix for any data stored in Redis.
    """

    def calculate_redis_key(self, page_id: PageInstanceIdModel) -> str:
        """Create the redis key for given the page's name and
        parameter values.

        Parameters
        ----------
        page_id
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.

        Returns
        -------
        str
            The unique redis key for this combination of page name and
            parameter values for a given datastore.
        """
        return page_id.cache_key

    async def store_instance(
        self,
        page_id: PageInstanceIdModel,
        data: S,
        lifetime: int | None = None,
    ) -> None:
        """Store a pydantic object for a page instance.

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
        await super().store(key, data, lifetime=lifetime)

    async def get_instance(self, page_id: PageInstanceIdModel) -> S | None:
        """Get the data stored for a page instance, deserializing it into the
        Pydantic model type.

        Parameters
        ----------
        page_id
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.

        Returns
        -------
        pydantic.BaseModel | None
            The dataset, as a Pydantic model. If the dataset is not found at
            the key, `None` is returned.
        """
        key = self.calculate_redis_key(page_id)
        return await super().get(key)

    async def iter_keys_for_page(self, page_name: str) -> AsyncIterable[str]:
        """Iterate over all keys for a page.

        Parameters
        ----------
        page_name
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).

        Yields
        ------
        str
            Yields keys for a page.
        """
        pattern = f"{page_name}/*"
        async for key in super().scan(pattern):
            yield key

    async def delete_instance(self, page_id: PageInstanceIdModel) -> bool:
        """Delete a dataset for a specific page instance.

        Parameters
        ----------
        key
            The key where the data is stored.

        Returns
        -------
        bool
            `True` if a record was deleted, `False` otherwise.
        """
        key = self.calculate_redis_key(page_id)
        return await super().delete(key)
