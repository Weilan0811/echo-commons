import sqlite3
from datetime import datetime

from echo_commons.agents.contracts.recovery import (
    FailureCategory,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import AppliedRecovery, RecoveryPolicy, decision
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.social.contracts import ParticipationResult, SocialLifecyclePort

REVIEW_HINTS = {
    "thought_too_long": "请缩短 thought，使其符合长度限制。",
    "utterance_too_long": "请缩短 utterance，使其符合长度限制。",
}


class ConversationRecovery:
    def __init__(
        self,
        policy: RecoveryPolicy,
        recorder: ExecutionRecorder,
        repository: ConversationQueueRepository,
        lifecycle: SocialLifecyclePort,
    ) -> None:
        self.policy, self.recorder, self.repository = policy, recorder, repository
        self.lifecycle = lifecycle

    classify = staticmethod(RecoveryPolicy.classify)

    def review(self, code: str) -> TaskRecoveryDecision:
        if code in REVIEW_HINTS:
            return decision(
                code, FailureCategory.REVIEW, RecoveryAction.RETRY_TASK, hint=REVIEW_HINTS[code]
            )
        if code == "community_paused":
            return decision(code, FailureCategory.SOURCE, RecoveryAction.DEFER)
        if code in ("member_left", "conversation_archived", "lease_expired", "source_replaced"):
            return decision(code, FailureCategory.LEASE, RecoveryAction.IGNORE)
        category = (
            FailureCategory.HARNESS
            if code == "invocation_identity_mismatch"
            else FailureCategory.REVIEW
        )
        return decision(code, category)

    def hint(self, connection: sqlite3.Connection, task_id: str) -> str | None:
        return self.policy.hint(
            self.recorder.repository.latest(connection, "conversation_reply", task_id)
        )

    def apply(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        recovery: TaskRecoveryDecision,
        now: datetime,
        *,
        expired: bool = False,
        observation: ExecutionObservation | None = None,
    ) -> AppliedRecovery | None:
        row = connection.execute(
            "SELECT * FROM conversation_tasks WHERE task_id=?", (lease.task_id,)
        ).fetchone()
        if not expired and self.repository.owned(connection, lease, now) is None:
            self.recorder.record(
                connection,
                lease,
                "result_ignored",
                ExecutionEventPayload(reason_code="lease_lost"),
                now,
            )
            return None
        if recovery.failure.code in ("agent_suspended", "agent_cancelled"):
            status = connection.execute(
                "SELECT status FROM communities WHERE community_id=?", (row["community_id"],)
            ).fetchone()[0]
            recovery = (
                self.review("community_paused")
                if status == "paused"
                else decision("agent_run_state_invalid", FailureCategory.HARNESS)
            )
        applied = self.policy.plan(recovery, lease.attempt, now)
        code = applied.decision.failure.code
        state = applied.task_state
        if code == "community_paused":
            state = "suspended"
        elif code in ("member_left", "conversation_archived", "source_replaced"):
            state = "cancelled"
        elif applied.action is RecoveryAction.IGNORE:
            self.recorder.record(
                connection, lease, "result_ignored", ExecutionEventPayload(recovery=applied), now
            )
            return applied
        applied = applied.model_copy(
            update={
                "task_state": state,
                "next_attempt_at_utc": applied.next_attempt_at_utc
                if state == "retry_wait"
                else None,
                "effective_wait_seconds": applied.effective_wait_seconds
                if state == "retry_wait"
                else None,
            }
        )
        self.repository.release(
            connection, lease.task_id, state, now, applied.next_attempt_at_utc or now, code
        )
        if state in ("failed", "cancelled"):
            self.lifecycle.task_finished(
                connection,
                ParticipationResult(
                    row["social_turn_id"],
                    row["character_id"],
                    state,
                    state,
                ),
                now,
            )
        self.recorder.record(
            connection,
            lease,
            "recovery_applied",
            self.recorder.recovery_payload(connection, lease, applied, observation),
            now,
        )
        return applied
