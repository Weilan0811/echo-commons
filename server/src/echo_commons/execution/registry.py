from collections.abc import Callable

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory, TaskRecoveryDecision
from echo_commons.execution.contracts import TaskHandler
from echo_commons.execution.recovery import RecoveryPolicy
from echo_commons.execution.scheduling import QueueRegistration


class TaskRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._classifiers: dict[str, Callable[[Exception], TaskRecoveryDecision]] = {}
        self.queue_registrations = []
        self.lanes = {}

    def register_queue(self, queue, lanes):
        if self.lanes.keys() & lanes.keys():
            raise ValueError("Task queue kinds must be registered once")
        self.queue_registrations.append(QueueRegistration(queue, lanes))
        self.lanes.update(lanes)

    def register(
        self,
        kind: str,
        handler: TaskHandler,
        classifier: Callable[[Exception], TaskRecoveryDecision],
    ) -> None:
        if not kind.strip() or kind in self._handlers:
            raise ValueError("Task kinds must be nonempty and registered once")
        self._handlers[kind] = handler
        self._classifiers[kind] = classifier

    def resolve(self, kind: str) -> TaskHandler:
        if kind not in self._handlers:
            raise ExecutionError("task_handler_not_registered", FailureCategory.CONFIGURATION)
        return self._handlers[kind]

    def classify(self, kind: str, error: Exception) -> TaskRecoveryDecision:
        return self._classifiers.get(kind, RecoveryPolicy.classify)(error)
