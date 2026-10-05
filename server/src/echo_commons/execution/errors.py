from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction


class ExecutionDeferred(ExecutionError):
    def __init__(self, code: str = "reflection_temporarily_unavailable") -> None:
        super().__init__(code, FailureCategory.SOURCE, RecoveryAction.DEFER)
