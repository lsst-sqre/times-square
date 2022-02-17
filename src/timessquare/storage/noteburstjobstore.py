"""A Redis-based cache of outstanding noteburst notebook execution jobs."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import aioredis

from timessquare.domain.noteburstjob import NoteburstJobModel

from .redisutils import calculate_key


class NoteburstJobStore:
    """The noteburst job store keeps track of open notebook execution job
    requests for a given page and set of parameters.
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

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
        key = NoteburstJobStore.calculate_key(
            page_name=page_name, parameters=parameters
        )
        serialized_data = job.json()
        await self._redis.set(key, serialized_data, ex=lifetime)

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
        key = NoteburstJobStore.calculate_key(
            page_name=page_name, parameters=parameters
        )
        serialized_data = await self._redis.get(key)
        if not serialized_data:
            return None

        return NoteburstJobModel.parse_raw(serialized_data.decode())

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
        key = NoteburstJobStore.calculate_key(
            page_name=page_name, parameters=parameters
        )
        count = await self._redis.delete(key)
        return count > 0

    @staticmethod
    def calculate_key(*, page_name: str, parameters: Mapping[str, Any]) -> str:
        """Create the redis key for a NoteburstJobStore given the page's name
        and parameter values.

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
            prefix="noteburst", page_name=page_name, parameters=parameters
        )
