"""Arq queue test doubles."""

from __future__ import annotations

from typing import Any, override

from safir.arq import JobMetadata, MockArqQueue

__all__ = ["RecordingArqQueue"]


class RecordingArqQueue(MockArqQueue):
    """A `~safir.arq.MockArqQueue` that records the tasks enqueued on it.

    Webhook handler tests assert on the task name and keyword arguments a
    handler enqueues, which `~safir.arq.MockArqQueue` only keeps in private
    state.

    Attributes
    ----------
    calls
        One ``(task_name, task_kwargs)`` tuple per `enqueue` call, in order.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @override
    async def enqueue(
        self,
        task_name: str,
        *task_args: Any,
        _queue_name: str | None = None,
        **task_kwargs: Any,
    ) -> JobMetadata:
        self.calls.append((task_name, task_kwargs))
        return await super().enqueue(
            task_name, *task_args, _queue_name=_queue_name, **task_kwargs
        )
