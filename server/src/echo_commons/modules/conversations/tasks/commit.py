import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.output import CharacterMessageProposal, expression_message
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.conversations.domain.message import Message, MessageVisibility
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.expression import ExpressionService
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery
from echo_commons.modules.conversations.tasks.review import ConversationReview
from echo_commons.modules.social.contracts import ParticipationResult, SocialLifecyclePort
from echo_commons.modules.social.repository import SocialRepository


@dataclass(frozen=True, slots=True)
class CommitReceipt:
    result_id: str
    outcome: ExecutionOutcome
    message_id: str | None = None


@dataclass
class ConversationCommit:
    database: Database
    tasks: ConversationTaskRepository
    queue: ConversationQueueRepository
    results: ConversationResultRepository
    review: ConversationReview
    conversations: ConversationRepository
    messages: MessageRepository
    social: SocialRepository
    recovery: ConversationRecovery
    lifecycle: SocialLifecyclePort
    expressions: ExpressionService

    def commit(
        self, lease: TaskLease, invocation: AgentInvocation, result: AgentRunResult
    ) -> CommitReceipt:
        with self.database.transaction() as connection:
            return self.commit_in(connection, lease, invocation, result)

    def commit_in(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        invocation: AgentInvocation,
        result: AgentRunResult,
    ) -> CommitReceipt:
        if not connection.in_transaction:
            raise RuntimeError("Expression commits require a caller-owned transaction")
        if result.status not in (AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL):
            raise ValueError("Only generated or silent results enter proposal review")
        now = datetime.now(UTC)
        existing = self.results.by_attempt(connection, lease.task_id, lease.attempt)
        if existing is not None:
            return CommitReceipt(existing["result_id"], ExecutionOutcome(Disposition.IGNORED))
        task = self.tasks.get(connection, lease.task_id)
        owned = self.queue.owned(connection, lease, now)
        code = (
            "lease_expired"
            if owned is None
            else self.review.check(connection, lease, task, invocation, result, now)
        )
        expired = code in (
            "lease_expired",
            "community_paused",
            "member_left",
            "conversation_archived",
            "source_replaced",
        )
        status = "expired" if expired else "rejected" if code else "approved"
        result_id = self.results.add(connection, lease, result, status, code or "approved", now)
        if code is not None:
            self.recovery.apply(connection, lease, self.recovery.review(code), now)
            return CommitReceipt(
                result_id,
                ExecutionOutcome(Disposition.IGNORED if owned is None else Disposition.HANDLED),
            )
        scope = invocation.context.scope
        turn = self.social.get(connection, task["community_id"], task["social_turn_id"])
        original_audience, visibility = turn.audience, MessageVisibility(turn.visibility)
        members = {
            member.membership_id
            for member in self.conversations.members(connection, task["conversation_id"])
        }
        audience = tuple(sorted(set(original_audience) & members))
        if task["membership_id"] not in audience:
            raise ValueError("Approved character is outside original audience")
        message = None
        if result.status is AgentRunStatus.COMPLETED:
            message, _ = self.save_expression_in(
                connection,
                invocation.context,
                expression_message(result.output.payload),
                result_id=result_id,
                audience=audience,
                visibility=visibility,
                trace_id=lease.trace_id,
                now=now,
            )
        message_id = message.message_id if message else None
        self.queue.release(connection, lease.task_id, "completed", now, now, None)
        self.lifecycle.task_finished(
            connection,
            ParticipationResult(
                scope.social_turn_id,
                task["character_id"],
                "completed",
                "message" if message_id else "silent",
                message,
                task["membership_id"],
                scope.observation_upper_sequence,
            ),
            now,
        )
        enqueue_trace(
            connection,
            str(uuid4()),
            lease.trace_id,
            "task.completed",
            "task",
            lease.task_id,
            {"result_id": result_id, "message_id": message_id, "attempt": lease.attempt},
            now,
        )
        self.recovery.recorder.record(
            connection,
            lease,
            "completed",
            ExecutionEventPayload(observation=self.recovery.recorder.observation(result)),
            now,
            str(result.invocation_id),
        )
        return CommitReceipt(result_id, ExecutionOutcome(Disposition.COMPLETED), message_id)

    def save_expression_in(
        self,
        connection: sqlite3.Connection,
        snapshot: ContextSnapshot,
        proposal: CharacterMessageProposal,
        *,
        result_id: str,
        audience: tuple[str, ...],
        visibility: MessageVisibility,
        trace_id: str,
        now: datetime,
    ) -> tuple[Message, str | None]:
        return self.expressions.save_in(
            connection,
            snapshot,
            proposal,
            result_id=result_id,
            audience=audience,
            visibility=visibility,
            trace_id=trace_id,
            now=now,
        )
