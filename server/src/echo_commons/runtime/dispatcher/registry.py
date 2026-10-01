"""Task-kind to handler registration without dispatcher branching."""

from __future__ import annotations

from echo_server.runtime.dispatcher.contracts import TaskHandler


class TaskHandlerRegistry:
    """Own the explicit set of task handlers available in one Runtime."""

    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, handler: TaskHandler) -> None:
        if handler.task_kind in self._handlers:
            raise ValueError(f"task handler already registered: {handler.task_kind}")
        self._handlers[handler.task_kind] = handler

    def resolve(self, task_kind: str) -> TaskHandler:
        try:
            return self._handlers[task_kind]
        except KeyError as exc:
            raise LookupError("task_handler_not_registered") from exc

    @property
    def task_kinds(self) -> tuple[str, ...]:
        return tuple(self._handlers)


__all__ = ["TaskHandlerRegistry"]
