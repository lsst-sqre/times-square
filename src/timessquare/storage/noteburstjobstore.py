"""A Redis-based cache of outstanding noteburst notebook execution jobs."""

from __future__ import annotations

from redis.asyncio import Redis

from timessquare.domain.noteburst import NoteburstJobModel
from timessquare.domain.page import PageInstanceIdModel

from .redisbase import RedisPageInstanceStore


class NoteburstJobStore(RedisPageInstanceStore[NoteburstJobModel]):
    """The noteburst job store keeps track of open notebook execution job
    requests for a given page and set of parameters.

    The associated domain model is
    `timessquare.domain.noteburst.NoteburstJobModel`.
    """

    def __init__(self, redis: Redis) -> None:
        super().__init__(
            redis=redis, key_prefix="noteburst/", datatype=NoteburstJobModel
        )

    async def store_job(
        self,
        *,
        job: NoteburstJobModel,
        page_id: PageInstanceIdModel,
        lifetime: int = 600,
    ) -> None:
        """Store a noteburst job request.

        Parameters
        ----------
        job
            The job record.
        page_id
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.
        lifetime
            The lifetime of the record, in seconds. The lifetime should be set
            so that if it elapses, it can be assumed that noteburst has failed
            to process the original job and that a new request can be sent.
        """
        await super().store_instance(page_id, job, lifetime=lifetime)
