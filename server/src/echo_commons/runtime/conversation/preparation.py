from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from uuid import UUID, uuid4

import aiosqlite

from echo_commons.domain.conversation import Conversation, ConversationKind, ConversationStatus
from echo_commons.domain.state import EligibilityRequest
from echo_commons.domain.task import ConversationTask, TaskStatus
from echo_commons.infrastructure.observability.logging import get_logger, log_event
from echo_commons.observability.trace import safe_trace_payload
from echo_commons.runtime.common import duration_ms as _duration_ms
from echo_commons.runtime.errors import (
    DatabaseUnavailableError,
    UnknownConversationError,
    UnsupportedCapabilityError,
)
from echo_commons.runtime.modules import ConversationModule

logger = get_logger("runtime")


class ConversationPreparationService:
    def __init__(self, runtime: ConversationModule) -> None:
        self.runtime = runtime

    async def _record_task_blocked(
        self,
        *,
        correlation_id: UUID,
        batch_id: UUID,
        reason_code: str,
        now: datetime,
        connection: aiosqlite.Connection,
        decision_code: str | None = None,
    ) -> None:
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind="task.blocked",
            entity_type="input_batch",
            entity_id=str(batch_id),
            payload=safe_trace_payload(
                "task.blocked",
                error_code=reason_code,
                decision_code=decision_code,
            ),
            created_at=now,
            connection=connection,
        )

    async def _resume_deferred_task_in_transaction(
        self,
        task: ConversationTask,
        *,
        conversation: Conversation,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> ConversationTask | None:
        """Resume a deferred task only after its blocking facts are current."""

        block_reason: str | None = None
        if not conversation.can_execute_agent:
            block_reason = "conversation_not_executable"
        elif conversation.context_version != task.context_version:
            block_reason = "context_expired"
        else:
            participants = await self.runtime.participants.list_active(
                task.account_id,
                task.conversation_id,
                connection,
            )
            if len(participants) != 1 or participants[0].character_id != task.character_id:
                block_reason = "participant_changed"
            else:
                world_state = await self.runtime.world_states.get(connection)
                character_state = await self.runtime.character_states.get(
                    task.character_id, connection
                )
                if world_state is None or character_state is None:
                    block_reason = "eligibility_state_missing"
                elif not self.runtime.response_eligibility.evaluate(
                    EligibilityRequest(
                        world_state=world_state,
                        character_state=character_state,
                    )
                ).allowed:
                    block_reason = "eligibility_unavailable"

        if block_reason is not None:
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="task.blocked",
                entity_type="task",
                entity_id=str(task.task_id),
                payload=safe_trace_payload("task.blocked", error_code=block_reason),
                created_at=now,
                connection=connection,
            )
            return None

        resumed = await self.runtime.runtime_tasks.resume(
            task.task_id,
            now_utc=now,
            connection=connection,
        )
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind="task.resumed",
            entity_type="task",
            entity_id=str(task.task_id),
            payload=safe_trace_payload("task.resumed", error_code=task.last_error_code),
            created_at=now,
            connection=connection,
        )
        return resumed

    async def _prepare_next_task_in_transaction(
        self,
        *,
        account_id: str,
        conversation_id: str,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> ConversationTask | None:
        conversation = await self.runtime.runtime_conversations.get(
            account_id,
            conversation_id,
            connection,
        )
        if conversation is None:
            raise UnknownConversationError(conversation_id)
        if conversation.kind is ConversationKind.GROUP:
            raise UnsupportedCapabilityError("group conversations are not supported")

        await self.runtime._seal_due_input_batches_in_transaction(
            account_id,
            conversation_id,
            now,
            correlation_id,
            connection,
        )
        waiting_batches = await self.runtime.input_batches.list_waiting(
            account_id,
            conversation_id,
            connection,
        )

        active_task = await self.runtime.runtime_tasks.get_active_for_conversation(
            account_id,
            conversation_id,
            connection,
        )
        if active_task is not None and active_task.status is TaskStatus.DEFERRED:
            resumed_task = await self._resume_deferred_task_in_transaction(
                active_task,
                conversation=conversation,
                now=now,
                correlation_id=correlation_id,
                connection=connection,
            )
            if resumed_task is not None:
                return resumed_task

        if not waiting_batches:
            return None

        first_batch = waiting_batches[0]
        if conversation.status is ConversationStatus.ARCHIVED:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="conversation_archived",
                now=now,
                connection=connection,
            )
            return None

        if active_task is not None:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="active_task_exists",
                now=now,
                connection=connection,
            )
            return None

        participants = await self.runtime.participants.list_active(
            account_id,
            conversation_id,
            connection,
        )
        if not participants:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="participant_missing",
                now=now,
                connection=connection,
            )
            return None
        if len(participants) != 1:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="participant_ambiguous",
                now=now,
                connection=connection,
            )
            return None

        world_state = await self.runtime.world_states.get(connection)
        if world_state is None:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="world_state_missing",
                now=now,
                connection=connection,
            )
            return None
        character_state = await self.runtime.character_states.get(
            participants[0].character_id,
            connection,
        )
        if character_state is None:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="character_state_missing",
                now=now,
                connection=connection,
            )
            return None

        decision = self.runtime.response_eligibility.evaluate(
            EligibilityRequest(world_state=world_state, character_state=character_state)
        )
        if not decision.allowed:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="response_ineligible",
                decision_code=",".join(decision.reason_codes),
                now=now,
                connection=connection,
            )
            return None

        messages = await self.runtime.runtime_messages.list_for_input_batches(
            account_id,
            conversation_id,
            tuple(batch.input_batch_id for batch in waiting_batches),
            connection,
        )
        preparation = self.runtime.input_preparation.prepare(waiting_batches, messages)
        if not preparation.accepted_batches:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code=preparation.blocked_reason or "input_not_ready",
                now=now,
                connection=connection,
            )
            return None

        if preparation.blocked_reason is not None:
            limited_batch = waiting_batches[len(preparation.accepted_batches)]
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="input_preparation.limited",
                entity_type="input_batch",
                entity_id=str(limited_batch.input_batch_id),
                payload=safe_trace_payload(
                    "input_preparation.limited",
                    error_code=preparation.blocked_reason,
                ),
                created_at=now,
                connection=connection,
            )

        input_max_sequence = preparation.input_max_message_sequence
        if input_max_sequence is None:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="input_not_ready",
                now=now,
                connection=connection,
            )
            return None
        context_max_sequence = await self.runtime.runtime_messages.max_sequence_through(
            account_id,
            conversation_id,
            input_max_sequence,
            connection,
        )
        if context_max_sequence < input_max_sequence:
            await self._record_task_blocked(
                correlation_id=correlation_id,
                batch_id=first_batch.input_batch_id,
                reason_code="context_boundary_not_ready",
                now=now,
                connection=connection,
            )
            return None

        task = ConversationTask.create(
            task_id=uuid4(),
            account_id=account_id,
            conversation_id=conversation_id,
            character_id=participants[0].character_id,
            input_max_message_sequence=input_max_sequence,
            context_max_message_sequence=context_max_sequence,
            world_state_version=decision.world_state_version,
            character_state_version=decision.character_state_version,
            context_version=conversation.context_version,
            trace_id=correlation_id,
            now_utc=now,
        )
        await self.runtime.runtime_tasks.create(task, connection=connection)
        for batch in preparation.accepted_batches:
            await self.runtime.input_batches.assign(
                batch.input_batch_id,
                task_id=task.task_id,
                now_utc=now,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="input_batch.assigned",
                entity_type="input_batch",
                entity_id=str(batch.input_batch_id),
                payload=safe_trace_payload("input_batch.assigned"),
                created_at=now,
                connection=connection,
            )
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind="task.created",
            entity_type="task",
            entity_id=str(task.task_id),
            payload=safe_trace_payload("task.created", context_version=task.context_version),
            created_at=now,
            connection=connection,
        )
        return task

    async def prepare_next_task(
        self,
        *,
        account_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ConversationTask | None:
        """Create one isolated S2.5 task from the earliest waiting batch prefix."""

        await self.runtime.ensure_started()
        account = account_id or self.runtime.settings.account_id
        conversation = conversation_id or self.runtime.settings.default_conversation_id
        now = self.runtime.clock()
        correlation_id = uuid4()
        started_at = perf_counter()
        try:
            async with self.runtime.database.transaction(immediate=True) as connection:
                task = await self._prepare_next_task_in_transaction(
                    account_id=account,
                    conversation_id=conversation,
                    now=now,
                    correlation_id=correlation_id,
                    connection=connection,
                )
        except (UnknownConversationError, UnsupportedCapabilityError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "task.preparation_rejected",
                correlation_id=correlation_id,
                account_id=account,
                conversation_id=conversation,
                error_code=exc.code,
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "task.preparation_failed",
                correlation_id=correlation_id,
                account_id=account,
                conversation_id=conversation,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("S2.5 task could not be prepared") from exc

        if task is not None:
            if self.runtime.wakeup is not None:
                self.runtime.wakeup.set()
            log_event(
                logger,
                logging.INFO,
                "task.created",
                correlation_id=correlation_id,
                account_id=account,
                conversation_id=conversation,
                task_id=task.task_id,
                duration_ms=_duration_ms(started_at),
            )
        else:
            log_event(
                logger,
                logging.DEBUG,
                "task.not_ready",
                correlation_id=correlation_id,
                account_id=account,
                conversation_id=conversation,
                duration_ms=_duration_ms(started_at),
            )
        return task


__all__ = ["ConversationPreparationService"]
