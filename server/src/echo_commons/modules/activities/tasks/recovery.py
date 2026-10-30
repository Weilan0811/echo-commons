from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.execution.recovery import RecoveryPolicy, decision
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysisError

REVIEW_HINT = (
    "请重新核对冻结输入中的合法动作、全部待处理消息与事件，以及意图的可见来源。"
    "需要落子时必须给出合法动作，沉默只影响表达。"
)


class ActivityRecovery:
    def __init__(self, policy, recorder, tasks):
        self.policy, self.recorder, self.tasks = policy, recorder, tasks

    @staticmethod
    def classify(error):
        if isinstance(error, GameplayAnalysisError):
            return decision(
                error.code,
                FailureCategory.PROVIDER,
                RecoveryAction.RETRY_TASK if error.retryable else RecoveryAction.FAIL,
            )
        return RecoveryPolicy.classify(error)

    def source(self, code):
        return decision(
            code,
            FailureCategory.SOURCE,
            RecoveryAction.DEFER
            if code in ("community_paused", "character_unavailable")
            else RecoveryAction.IGNORE,
        )

    def apply(self, connection, lease, recovery, now, *, expired=False, observation=None):
        if not expired and self.tasks.owned(connection, lease, now) is None:
            return None
        applied = self.policy.plan(recovery, lease.attempt, now)
        state = applied.task_state
        if recovery.failure.code in (
            "community_paused",
            "character_unavailable",
            "agent_suspended",
        ):
            state = "suspended"
        elif applied.action is RecoveryAction.IGNORE:
            state = "cancelled"
        applied = applied.model_copy(update={"task_state": state})
        self.tasks.release(
            connection,
            lease.task_id,
            state,
            now,
            applied.next_attempt_at_utc or now,
            recovery.failure.code,
        )
        self.recorder.record(
            connection,
            lease,
            "recovery_applied",
            self.recorder.recovery_payload(connection, lease, applied, observation),
            now,
        )
        return applied
