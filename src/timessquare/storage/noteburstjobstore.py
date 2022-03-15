"""A Redis-based cache of outstanding noteburst notebook execution jobs."""

from __future__ import annotations

from typing import Any, AsyncIterable, Mapping, Optional

import aioredis

from timessquare.domain.noteburstjob import NoteburstJobModel

from .redisbase import RedisStore


class NoteburstJobStore:
    """The noteburst job store keeps track of open notebook execution job
    requests for a given page and set of parameters.

    The associated domain model is
    `timessquare.domain.noteburstjob.NoteburstJobModel`.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = RedisStore[NoteburstJobModel](
            redis=redis, key_prefix="noteburst", datatype=NoteburstJobModel
        )

    async def store(
        self,
        *,
        job: NoteburstJobModel,
        page_name: str,
        parameters: Mapping[str, Any],
        lifetime: int = 600,
    ) -> None:
        """Store a noteburst job request.

        Parameters
        ----------
        job : `timessquare.domain.noteburstjob.NoteburstJobModel`
            The job record.
        page_name : str
            The name of the page (corresponds to
            `timessquare.domain.page.PageModel.name`).
        parameters : dict
            The parameter values, keyed by the parameter names, with values as
            cast Python types
            (`timessquare.domain.page.PageParameterSchema.cast_value`).
        lifetime : int
            The lifetime of the record, in seconds. The lifetime should be set
            so that if it elapses, it can be assumed that noteburst has failed
            to process the original job and that a new request can be sent.
        """
        key = self._redis.calculate_redis_key(
            page_name=page_name, parameters=parameters
        )
        await self._redis.store(key, job, lifetime=lifetime)

    async def get(
        self, *, page_name: str, parameters: Mapping[str, Any]
    ) -> Optional[NoteburstJobModel]:
        """Get the job request for page and a given set of template parameters,
        if an outstanding job is available.

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
        job : `timessquare.domain.noteburstjob.NoteburstJobModel` or `None`
            The noteburst job is one is outstanding, or None if such a job
            doesn't exist.
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
        """Delete the job request record for a page and a given set of
        template parameters, if available.

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
        key = self._redis.calculate_redis_key(
            page_name=page_name, parameters=parameters
        )
        return await self._redis.delete(key)
