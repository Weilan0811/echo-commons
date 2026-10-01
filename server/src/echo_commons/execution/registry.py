from echo_commons.execution.contracts import TaskHandler


class TaskRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, kind: str, handler: TaskHandler) -> None:
        if not kind.strip() or kind in self._handlers:
            raise ValueError("Task kinds must be nonempty and registered once")
        self._handlers[kind] = handler

    def resolve(self, kind: str) -> TaskHandler:
        return self._handlers[kind]
