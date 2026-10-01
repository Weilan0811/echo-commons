from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from echo_commons.domain.task import ConversationTask
from echo_commons.runtime.dispatcher.contracts import (
    TaskDisposition,
    TaskExecutionResult,
    TaskHandler,
    TaskLease,
)


class ConversationTaskHandler(TaskHandler):
    """Bridge one generic lease to the fenced conversation execution service."""

    task_kind = "conversation.reply"

    def __init__(self, execute_task: Callable[[UUID], Awaitable[bool]]) -> None:
        self._execute_task = execute_task

    async def execute(self, lease: TaskLease) -> TaskExecutionResult:
        task = lease.payload
        if not isinstance(task, ConversationTask):
            raise TypeError("conversation task lease has an invalid payload")
        handled = await self._execute_task(task.task_id)
        return TaskExecutionResult(
            disposition=(TaskDisposition.COMMITTED if handled else TaskDisposition.STALE)
        )


__all__ = ["ConversationTaskHandler"]
