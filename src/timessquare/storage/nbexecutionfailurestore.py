"""A Redis-based cache of terminal notebook execution failures."""

from __future__ import annotations

from redis.asyncio import Redis

from ..domain.executionoutcome import NotebookExecutionFailure
from ..domain.page import PageInstanceIdModel
from .redisbase import RedisPageInstanceStore

__all__ = ["NbExecutionFailureStore"]

DEFAULT_FAILURE_LIFETIME = 600
"""Default lifetime, in seconds, for a cached execution failure.

The lifetime is finite so that a transient infrastructure failure becomes
retryable once it expires, while still being long enough to prevent a broken
notebook from triggering a fresh Noteburst execution on every ``htmlstatus``
poll (a re-execution storm).
"""


class NbExecutionFailureStore(
    RedisPageInstanceStore[NotebookExecutionFailure]
):
    """A store of terminal notebook execution failures, keyed by page
    instance.

    A cached failure short-circuits re-execution: while a failure is cached,
    the page service returns the terminal failure outcome instead of
    requesting a new Noteburst execution. The associated domain model is
    `timessquare.domain.executionoutcome.NotebookExecutionFailure`.
    """

    def __init__(self, redis: Redis) -> None:
        super().__init__(
            redis=redis,
            key_prefix="execution-failure/",
            datatype=NotebookExecutionFailure,
        )

    async def store_failure(
        self,
        *,
        failure: NotebookExecutionFailure,
        page_id: PageInstanceIdModel,
        lifetime: int = DEFAULT_FAILURE_LIFETIME,
    ) -> None:
        """Cache a terminal execution failure for a page instance.

        Parameters
        ----------
        failure
            The failure description.
        page_id
            Identifier of the page instance, composed of the page's name
            and the values the page instance is rendered with.
        lifetime
            The lifetime of the record, in seconds. After it elapses the
            failure is retried on the next request.
        """
        await super().store_instance(page_id, failure, lifetime=lifetime)
