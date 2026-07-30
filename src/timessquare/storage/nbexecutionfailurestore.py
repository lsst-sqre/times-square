"""A Redis-based cache of terminal notebook execution failures."""

from __future__ import annotations

from redis.asyncio import Redis

from ..domain.executionoutcome import NotebookExecutionFailure
from ..domain.page import PageInstanceIdModel
from .redisbase import RedisPageInstanceStore

__all__ = ["NbExecutionFailureStore"]

DEFAULT_FAILURE_LIFETIME = 600
"""Fallback lifetime, in seconds, for a cached execution failure.

Deployments configure the lifetime with
`timessquare.config.Config.execution_failure_lifetime`
(``TS_EXECUTION_FAILURE_LIFETIME``); this constant applies only when a store
is constructed without a ``default_lifetime``.

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

    Parameters
    ----------
    redis
        The Redis client.
    default_lifetime
        The default lifetime, in seconds, applied to cached failures when
        `store_failure` is not given an explicit ``lifetime``.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        default_lifetime: int = DEFAULT_FAILURE_LIFETIME,
    ) -> None:
        super().__init__(
            redis=redis,
            key_prefix="execution-failure/",
            datatype=NotebookExecutionFailure,
        )
        self._default_lifetime = default_lifetime

    async def store_failure(
        self,
        *,
        failure: NotebookExecutionFailure,
        page_id: PageInstanceIdModel,
        lifetime: int | None = None,
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
            failure is retried on the next request. If `None`, the store's
            default lifetime is used.
        """
        await super().store_instance(
            page_id,
            failure,
            lifetime=(
                self._default_lifetime if lifetime is None else lifetime
            ),
        )
