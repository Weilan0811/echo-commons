from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.domain.message import Message, MessageVisibility
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.conversations.services.events import message_created
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery
from echo_commons.modules.conversations.tasks.review import ConversationReview
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.social.contracts import ParticipationResult, SocialLifecyclePort
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef


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
    communities: CommunityReader
    conversations: ConversationRepository
    messages: MessageRepository
    batches: InputCollector
    indexer: MemoryIndexing
    thoughts: ThoughtRepository
    social: SocialRepository
    recovery: ConversationRecovery
    lifecycle: SocialLifecyclePort

    def commit(
        self, lease: TaskLease, invocation: AgentInvocation, result: AgentRunResult
    ) -> CommitReceipt:
        if result.status not in (AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL):
            raise ValueError("Only generated or silent results enter proposal review")
        with self.database.transaction() as connection:
            now = datetime.now(UTC)
            existing = self.results.by_attempt(connection, lease.task_id, lease.attempt)
            if existing is not None:
                return CommitReceipt(
                    existing["result_id"],
                    ExecutionOutcome(Disposition.IGNORED),
                )
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
            turn = self.social.get(connection, task["community_id"], task["social_turn_id"])
            members = {
                member.membership_id
                for member in self.conversations.members(connection, task["conversation_id"])
            }
            audience = tuple(sorted(set(turn.audience) & members))
            if task["membership_id"] not in audience:
                raise ValueError("Approved character is outside original turn audience")
            message_id = None
            message, batch_id = None, None
            if result.status is AgentRunStatus.COMPLETED:
                proposal = result.output.payload
                message_id = str(uuid4())
                message = Message(
                    message_id,
                    task["community_id"],
                    task["conversation_id"],
                    self.conversations.allocate_sequence(connection, task["conversation_id"], now),
                    ActorRef("character", task["character_id"]),
                    task["membership_id"],
                    proposal.utterance,
                    MessageVisibility(turn.visibility),
                    audience,
                    (),
                    invocation.context.reply_target(proposal.reply_to).message_id
                    if proposal.reply_to is not None
                    else None,
                    None,
                    turn.social_turn_id,
                    result_id,
                    lease.trace_id,
                    now,
                )
                self.messages.add(connection, message)
                message_created(connection, message)
                batch_id = self.batches.collect(connection, message, quiet_seconds=0)
                self.indexer.message(connection, message)
                if proposal.thought.strip():
                    community = self.communities.get(connection, task["community_id"])
                    game_day = (
                        community.world_time_utc.astimezone(ZoneInfo(community.timezone))
                        .date()
                        .isoformat()
                    )
                    self.thoughts.add(
                        connection,
                        result_id,
                        task["community_id"],
                        task["character_id"],
                        task["conversation_id"],
                        game_day,
                        proposal.thought,
                        now,
                    )
            self.queue.release(connection, lease.task_id, "completed", now, now, None)
            self.lifecycle.task_finished(
                connection,
                ParticipationResult(
                    turn.social_turn_id,
                    task["character_id"],
                    "completed",
                    "message" if message_id else "silent",
                    message,
                    batch_id,
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
