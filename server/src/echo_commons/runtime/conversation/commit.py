"""Atomic T3 review, result, message, and task commit workflow."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import aiosqlite

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    CharacterMessageProposal,
    InvocationPurpose,
    ProposalEnvelope,
    ProposalOutput,
)
from echo_server.domain.conversation import ConversationKind, ConversationStatus
from echo_server.domain.input_batch import InputBatch
from echo_server.domain.memory import Thought
from echo_server.domain.messages import Message
from echo_server.domain.proposals import ProposalDecision
from echo_server.domain.result import AgentResult, AgentResultStatus, project_bubbles
from echo_server.domain.state import EligibilityRequest
from echo_server.domain.task import ConversationTask, TaskStatus
from echo_server.observability.logging import get_logger, log_event
from echo_server.observability.trace import safe_trace_payload
from echo_server.runtime.errors import InvalidAgentRunError
from echo_server.runtime.modules import ConversationModule
from echo_server.runtime.proposals.registry import ProposalReviewContext

logger = get_logger("runtime")


class ConversationCommitService:
    def __init__(self, runtime: ConversationModule) -> None:
        self.runtime = runtime

    @staticmethod
    def _redacted_proposal_json(proposal: ProposalEnvelope) -> str:
        """Serialize an audit-safe proposal without private character thought."""

        payload = proposal.model_dump(mode="json")
        proposal_payload = payload.get("payload")
        if isinstance(proposal_payload, dict):
            proposal_payload.pop("thought", None)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _agent_result_from_run(
        task: ConversationTask,
        invocation: AgentInvocation,
        run_result: AgentRunResult,
        proposal: ProposalEnvelope | None,
        now: datetime,
    ) -> AgentResult:
        if proposal is None:
            payload_json = json.dumps(
                {
                    "kind": "no_proposal",
                    "stopReason": run_result.stop_reason.value,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            result_kind = "no_proposal"
            schema_version = "v1"
        else:
            payload_json = ConversationCommitService._redacted_proposal_json(proposal)
            result_kind = proposal.kind.value
            schema_version = (
                run_result.output.contract.version
                if isinstance(run_result.output, ProposalOutput)
                else "v1"
            )
        return AgentResult(
            result_id=uuid4(),
            task_id=task.task_id,
            attempt_no=task.attempt_count,
            agent_id=run_result.agent_id,
            agent_kind=run_result.agent_kind,
            invocation_id=invocation.identity.invocation_id,
            result_kind=result_kind,
            schema_version=schema_version,
            context_version=invocation.context_input.snapshot_id,
            payload_json=payload_json,
            created_at_utc=now,
        )

    async def _save_approved_thought(
        self,
        task: ConversationTask,
        result: AgentResult,
        proposal: ProposalEnvelope,
        *,
        game_day: str,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        """Persist a non-empty thought attached to an approved character reply."""

        payload = proposal.payload
        if not isinstance(payload, CharacterMessageProposal):
            return
        if not payload.thought.strip():
            return
        await self.runtime.thoughts.ensure(
            Thought(
                thought_id=uuid4(),
                result_id=result.result_id,
                conversation_id=task.conversation_id,
                account_id=task.account_id,
                character_id=task.character_id,
                game_day=game_day,
                content=payload.thought,
                created_at_utc=now,
            ),
            connection=connection,
        )

    async def _save_result_decision(
        self,
        result: AgentResult,
        *,
        decision: AgentResultStatus,
        decision_code: str,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> AgentResult:
        if decision is AgentResultStatus.APPROVED:
            decided = result.approve(decided_at_utc=now, decision_code=decision_code)
        elif decision is AgentResultStatus.REJECTED:
            decided = result.reject(decided_at_utc=now, decision_code=decision_code)
        elif decision is AgentResultStatus.EXPIRED:
            decided = result.expire(decided_at_utc=now, decision_code=decision_code)
        else:
            raise ValueError("pending is not a terminal AgentResult decision")
        await self.runtime.runtime_results.save_decision(decided, connection=connection)
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind=f"agent_result.{decided.status.value}",
            entity_type="agent_result",
            entity_id=str(decided.result_id),
            payload=safe_trace_payload(
                f"agent_result.{decided.status.value}",
                decision_code=decision_code,
            ),
            created_at=now,
            connection=connection,
        )
        return decided

    async def _cover_task_batches(
        self,
        task_id: UUID,
        *,
        correlation_id: UUID,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> tuple[InputBatch, ...]:
        batches = await self.runtime.input_batches.list_for_task(task_id, connection)
        if not batches:
            raise LookupError("task_input_batches_not_found")
        for batch in batches:
            await self.runtime.input_batches.cover(
                batch.input_batch_id,
                now_utc=now,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="input_batch.covered",
                entity_type="input_batch",
                entity_id=str(batch.input_batch_id),
                payload=safe_trace_payload("input_batch.covered"),
                created_at=now,
                connection=connection,
            )
        return batches

    async def _retry_or_fail_task_in_transaction(
        self,
        task: ConversationTask,
        *,
        error_code: str,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> bool:
        failed = task.attempt_count >= self.runtime.settings.max_agent_attempts
        available_at = (
            now if failed else now + timedelta(seconds=self.runtime.settings.retry_backoff_seconds)
        )
        await self.runtime.runtime_tasks.retry_or_fail(
            task.task_id,
            worker_id=self.runtime.worker_id,
            now_utc=now,
            available_at_utc=available_at,
            error_code=error_code,
            max_attempts=self.runtime.settings.max_agent_attempts,
            attempt_count=task.attempt_count,
            lease_generation=task.lease_generation,
            connection=connection,
        )
        if failed:
            await self._fail_task_batches_in_transaction(
                task,
                error_code=error_code,
                now=now,
                correlation_id=correlation_id,
                connection=connection,
            )
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind="task.failed" if failed else "task.retry_scheduled",
            entity_type="task",
            entity_id=str(task.task_id),
            payload=safe_trace_payload(
                "task.failed" if failed else "task.retry_scheduled",
                error_code=error_code,
                attempt_count=task.attempt_count,
            ),
            created_at=now,
            connection=connection,
        )
        return failed

    async def _fail_task_batches_in_transaction(
        self,
        task: ConversationTask,
        *,
        error_code: str,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> None:
        for batch in await self.runtime.input_batches.list_for_task(task.task_id, connection):
            await self.runtime.input_batches.fail_terminally(
                batch.input_batch_id,
                now_utc=now,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="input_batch.terminal_failed",
                entity_type="input_batch",
                entity_id=str(batch.input_batch_id),
                payload=safe_trace_payload("input_batch.terminal_failed", error_code=error_code),
                created_at=now,
                connection=connection,
            )

    async def _fail_task_in_transaction(
        self,
        task: ConversationTask,
        *,
        error_code: str,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> bool:
        await self.runtime.runtime_tasks.fail(
            task.task_id,
            worker_id=self.runtime.worker_id,
            now_utc=now,
            error_code=error_code,
            attempt_count=task.attempt_count,
            lease_generation=task.lease_generation,
            connection=connection,
        )
        await self._fail_task_batches_in_transaction(
            task,
            error_code=error_code,
            now=now,
            correlation_id=correlation_id,
            connection=connection,
        )
        await self.runtime.task_traces.enqueue(
            trace_id=uuid4(),
            correlation_id=correlation_id,
            kind="task.failed",
            entity_type="task",
            entity_id=str(task.task_id),
            payload=safe_trace_payload(
                "task.failed",
                error_code=error_code,
                attempt_count=task.attempt_count,
            ),
            created_at=now,
            connection=connection,
        )
        return True

    async def commit_task_result(
        self,
        task_id: UUID,
        *,
        invocation: AgentInvocation,
        run_result: AgentRunResult,
        proposal: ProposalEnvelope | None,
        lease_generation: int,
    ) -> bool:
        """Review and atomically commit one completed S2.5 Agent attempt."""

        await self.runtime.ensure_started()
        now = self.runtime.clock()
        correlation_id = invocation.correlation.trace_id
        outcome = "ignored"
        try:
            async with self.runtime.database.transaction(immediate=True) as connection:
                task = await self.runtime.runtime_tasks.get(task_id, connection)
                if task is None:
                    outcome = "task_missing"
                elif (
                    task.status is not TaskStatus.PROCESSING
                    or task.lease_owner != self.runtime.worker_id
                    or task.attempt_count != invocation.identity.attempt
                    or not task.has_valid_lease(
                        worker_id=self.runtime.worker_id,
                        now_utc=now,
                        attempt_count=invocation.identity.attempt,
                        lease_generation=lease_generation,
                    )
                ):
                    outcome = "late"
                elif await self.runtime.runtime_results.get_for_task_attempt(
                    task.task_id, task.attempt_count, connection
                ):
                    outcome = "duplicate"
                else:
                    result = self._agent_result_from_run(
                        task,
                        invocation,
                        run_result,
                        proposal,
                        now,
                    )
                    await self.runtime.runtime_results.insert(result, connection=connection)
                    await self.runtime.task_traces.enqueue(
                        trace_id=uuid4(),
                        correlation_id=correlation_id,
                        kind="agent_result.created",
                        entity_type="agent_result",
                        entity_id=str(result.result_id),
                        payload=safe_trace_payload(
                            "agent_result.created",
                            context_version=result.context_version,
                        ),
                        created_at=now,
                        connection=connection,
                    )
                    batches = await self.runtime.input_batches.list_for_task(
                        task.task_id, connection
                    )
                    if not batches:
                        raise LookupError("task_input_batches_not_found")

                    conversation = await self.runtime.runtime_conversations.get(
                        task.account_id,
                        task.conversation_id,
                        connection,
                    )
                    block_reason: str | None = None
                    world_state = None
                    if conversation is None:
                        block_reason = "conversation_not_found"
                    elif conversation.kind is not ConversationKind.DIRECT:
                        block_reason = "conversation_not_executable"
                    elif conversation.status is ConversationStatus.ARCHIVED:
                        block_reason = "conversation_archived"
                    elif conversation.context_version != task.context_version:
                        block_reason = "context_expired"
                    else:
                        participants = await self.runtime.participants.list_active(
                            task.account_id,
                            task.conversation_id,
                            connection,
                        )
                        if (
                            len(participants) != 1
                            or participants[0].character_id != task.character_id
                        ):
                            block_reason = "participant_changed"
                        else:
                            world_state = await self.runtime.world_states.get(connection)
                            character_state = await self.runtime.character_states.get(
                                task.character_id,
                                connection,
                            )
                            if world_state is None or character_state is None:
                                block_reason = "eligibility_state_missing"
                            else:
                                decision = self.runtime.response_eligibility.evaluate(
                                    EligibilityRequest(
                                        world_state=world_state,
                                        character_state=character_state,
                                    )
                                )
                                if not decision.allowed:
                                    block_reason = "eligibility_changed"

                    if block_reason is not None:
                        await self._save_result_decision(
                            result,
                            decision=AgentResultStatus.EXPIRED,
                            decision_code=block_reason,
                            now=now,
                            correlation_id=correlation_id,
                            connection=connection,
                        )
                        await self.runtime.runtime_tasks.defer(
                            task.task_id,
                            worker_id=self.runtime.worker_id,
                            now_utc=now,
                            reason_code=block_reason,
                            attempt_count=task.attempt_count,
                            lease_generation=task.lease_generation,
                            connection=connection,
                        )
                        await self.runtime.task_traces.enqueue(
                            trace_id=uuid4(),
                            correlation_id=correlation_id,
                            kind="task.deferred",
                            entity_type="task",
                            entity_id=str(task.task_id),
                            payload=safe_trace_payload("task.deferred", error_code=block_reason),
                            created_at=now,
                            connection=connection,
                        )
                        outcome = "deferred"
                    elif run_result.status is AgentRunStatus.NO_PROPOSAL:
                        approved = await self._save_result_decision(
                            result,
                            decision=AgentResultStatus.APPROVED,
                            decision_code="no_proposal",
                            now=now,
                            correlation_id=correlation_id,
                            connection=connection,
                        )
                        await self._cover_task_batches(
                            task.task_id,
                            correlation_id=correlation_id,
                            now=now,
                            connection=connection,
                        )
                        await self.runtime.runtime_tasks.complete(
                            task.task_id,
                            worker_id=self.runtime.worker_id,
                            now_utc=now,
                            attempt_count=task.attempt_count,
                            lease_generation=task.lease_generation,
                            connection=connection,
                        )
                        await self.runtime.task_traces.enqueue(
                            trace_id=uuid4(),
                            correlation_id=correlation_id,
                            kind="task.completed",
                            entity_type="task",
                            entity_id=str(task.task_id),
                            payload=safe_trace_payload(
                                "task.completed",
                                decision_code=approved.decision_code,
                                stop_reason=run_result.stop_reason.value,
                            ),
                            created_at=now,
                            connection=connection,
                        )
                        outcome = "completed"
                    else:
                        if proposal is None:
                            raise InvalidAgentRunError("completed Agent Run has no Proposal")
                        review = self.runtime.reviewer.review(
                            proposal,
                            context=ProposalReviewContext(
                                expected_agent_id=invocation.identity.agent_id,
                                expected_agent_kind=invocation.identity.agent_kind,
                                expected_character_id=task.character_id,
                                expected_context_version=task.context_version,
                                actual_context_version=task.context_version,
                                task_status=task.status,
                                lease_owner=task.lease_owner,
                                worker_id=self.runtime.worker_id,
                                lease_valid=True,
                                proposal_processed=await self.runtime.runtime_results.has_approved(
                                    task.task_id,
                                    connection,
                                ),
                                expected_invocation_id=invocation.identity.invocation_id,
                                expected_invocation_purpose=InvocationPurpose.CONVERSATION_REPLY.value,
                            ),
                        )
                        if review.decision is ProposalDecision.APPROVED:
                            approved = await self._save_result_decision(
                                result,
                                decision=AgentResultStatus.APPROVED,
                                decision_code=review.code.value,
                                now=now,
                                correlation_id=correlation_id,
                                connection=connection,
                            )
                            bubble_texts = self.runtime.bubble_projector(proposal)
                            bubbles = project_bubbles(
                                approved,
                                bubble_texts,
                                reply_to_message_id=(
                                    proposal.payload.reply_to_message_id
                                    or invocation.context.trigger_message.message_id
                                ),
                            )
                            for bubble in bubbles:
                                stored_message = await self.runtime.runtime_messages.insert(
                                    Message.character(
                                        message_sequence=0,
                                        message_id=uuid4(),
                                        account_id=task.account_id,
                                        conversation_id=task.conversation_id,
                                        character_id=task.character_id,
                                        text=bubble.text,
                                        server_timestamp_utc=now,
                                        result_id=approved.result_id,
                                        bubble_index=bubble.bubble_index,
                                        reply_to_message_id=bubble.reply_to_message_id,
                                        trace_id=correlation_id,
                                        images=bubble.images,
                                    ),
                                    connection=connection,
                                )
                                await self.runtime.task_traces.enqueue(
                                    trace_id=uuid4(),
                                    correlation_id=correlation_id,
                                    kind="message.character_committed",
                                    entity_type="message",
                                    entity_id=str(stored_message.message_id),
                                    payload=safe_trace_payload("message.character_committed"),
                                    created_at=now,
                                    connection=connection,
                                )
                            await self._save_approved_thought(
                                task,
                                approved,
                                proposal,
                                # Account timezone is not persisted yet; the
                                # authoritative world UTC date is the stable
                                # game-day key until that account setting exists.
                                game_day=(
                                    world_state.world_time_utc.date().isoformat()
                                    if world_state is not None
                                    else now.date().isoformat()
                                ),
                                now=now,
                                connection=connection,
                            )
                            await self._cover_task_batches(
                                task.task_id,
                                correlation_id=correlation_id,
                                now=now,
                                connection=connection,
                            )
                            await self.runtime.runtime_tasks.complete(
                                task.task_id,
                                worker_id=self.runtime.worker_id,
                                now_utc=now,
                                attempt_count=task.attempt_count,
                                lease_generation=task.lease_generation,
                                connection=connection,
                            )
                            await self.runtime.task_traces.enqueue(
                                trace_id=uuid4(),
                                correlation_id=correlation_id,
                                kind="task.completed",
                                entity_type="task",
                                entity_id=str(task.task_id),
                                payload=safe_trace_payload(
                                    "task.completed",
                                    decision_code=review.code.value,
                                    context_version=task.context_version,
                                ),
                                created_at=now,
                                connection=connection,
                            )
                            outcome = "completed"
                        elif review.decision is ProposalDecision.EXPIRED:
                            await self._save_result_decision(
                                result,
                                decision=AgentResultStatus.EXPIRED,
                                decision_code=review.code.value,
                                now=now,
                                correlation_id=correlation_id,
                                connection=connection,
                            )
                            await self.runtime.runtime_tasks.defer(
                                task.task_id,
                                worker_id=self.runtime.worker_id,
                                now_utc=now,
                                reason_code=review.code.value,
                                attempt_count=task.attempt_count,
                                lease_generation=task.lease_generation,
                                connection=connection,
                            )
                            await self.runtime.task_traces.enqueue(
                                trace_id=uuid4(),
                                correlation_id=correlation_id,
                                kind="task.deferred",
                                entity_type="task",
                                entity_id=str(task.task_id),
                                payload=safe_trace_payload(
                                    "task.deferred",
                                    error_code=review.code.value,
                                ),
                                created_at=now,
                                connection=connection,
                            )
                            outcome = "deferred"
                        else:
                            await self._save_result_decision(
                                result,
                                decision=AgentResultStatus.REJECTED,
                                decision_code=review.code.value,
                                now=now,
                                correlation_id=correlation_id,
                                connection=connection,
                            )
                            await self._retry_or_fail_task_in_transaction(
                                task,
                                error_code=review.code.value,
                                now=now,
                                correlation_id=correlation_id,
                                connection=connection,
                            )
                            outcome = "failed_or_retry"
        except Exception:
            raise

        if outcome in {"late", "duplicate", "task_missing"}:
            await self.runtime._event(
                correlation_id,
                "agent_result.late" if outcome == "late" else "agent_result.ignored",
                "task",
                str(task_id),
                safe_trace_payload(
                    "agent_result.late" if outcome == "late" else "agent_result.ignored",
                    error_code=outcome,
                ),
            )
            return False
        log_event(
            logger,
            logging.INFO if outcome in {"completed", "deferred"} else logging.WARNING,
            "task.result_committed",
            correlation_id=correlation_id,
            task_id=task_id,
            outcome=outcome,
        )
        if outcome == "completed" and self.runtime.wakeup is not None:
            self.runtime.wakeup.set()
        return True

    @staticmethod
    def _proposal_from_run(
        run_result: AgentRunResult, invocation: AgentInvocation
    ) -> ProposalEnvelope | None:
        """Validate the Agent Run envelope before entering the T3 transaction."""

        ConversationCommitService._validate_run_identity(run_result, invocation)
        if run_result.status is AgentRunStatus.NO_PROPOSAL:
            if run_result.output is not None:
                raise InvalidAgentRunError("no_proposal Run cannot contain proposals")
            return None
        if run_result.status is not AgentRunStatus.COMPLETED:
            raise InvalidAgentRunError("Agent Run did not complete")
        if not isinstance(run_result.output, ProposalOutput):
            raise InvalidAgentRunError("ConversationTask requires exactly one Proposal")
        proposal = run_result.output.proposal
        if not isinstance(proposal.payload, CharacterMessageProposal):
            raise InvalidAgentRunError("ConversationTask requires a character message Proposal")
        return proposal

    @staticmethod
    def _validate_run_identity(
        run_result: AgentRunResult,
        invocation: AgentInvocation,
    ) -> None:
        if run_result.invocation_id != invocation.identity.invocation_id:
            raise InvalidAgentRunError("Agent Run returned a different invocation")
        if run_result.agent_id != invocation.identity.agent_id:
            raise InvalidAgentRunError("Agent Run returned a different agent")
        if run_result.agent_kind != invocation.identity.agent_kind:
            raise InvalidAgentRunError("Agent Run returned a different agent kind")


__all__ = ["ConversationCommitService"]
