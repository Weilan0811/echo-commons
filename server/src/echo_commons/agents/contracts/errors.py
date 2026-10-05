from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction


class ExecutionError(RuntimeError):
    def __init__(
        self, code: str, category: FailureCategory, action: RecoveryAction = RecoveryAction.FAIL
    ) -> None:
        self.code, self.category, self.action = code, category, action
        super().__init__(code)
