from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError

from echo_commons.agents.contracts import (
    CHARACTER_MESSAGE_OUTPUT_SCHEMA,
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    OutputContractRef,
    RecoveryAction,
)
from echo_commons.domain.task import ConversationTask, TaskStatus
from echo_commons.infrastructure.observability.logging import get_logger, log_event
from echo_commons.observability.trace import safe_trace_payload
from echo_commons.runtime.common import duration_ms as _duration_ms
from echo_commons.runtime.conversation.commit import ConversationCommitService
from echo_commons.runtime.dispatcher.lease import LeaseHeartbeat
from echo_commons.runtime.errors import InvalidAgentRunError, LeaseHeartbeatError, LeaseLostError
from echo_commons.runtime.modules import ConversationModule
from echo_commons.runtime.recovery import decide_agent_run
from echo_commons.infrastructure.models import resolve_agent_route

logger = get_logger("runtime")


class ConversationExecutionService:
    def __init__(
        self,
        runtime: ConversationModule,
        commit: ConversationCommitService,
    ) -> None:
        self.runtime = runtime
        self.commit = commit

    def _allowed_conversation_tools(self) -> tuple[str, ...]:
        """Intersect Agent-declared tools with Runtime-owned capabilities."""

        capabilities = getattr(self.runtime.agent, "capabilities", None)
        if capabilities is None:
            return ()
        purpose = capabilities.for_purpose(InvocationPurpose.CONVERSATION_REPLY)
        if purpose is None:
            return ()
        return purpose.allowed_tools

    async def _schedule_task_failure(
        self,
        task_id: UUID,
        correlation_id: UUID,
        error_code: str,
        *,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
        retryable: bool = True,
    ) -> None:
        now = self.runtime.clock()
        try:
            async with self.runtime.database.transaction(immediate=True) as connection:
                task = await self.runtime.runtime_tasks.get(task_id, connection)
                if (
                    task is None
                    or task.status is not TaskStatus.PROCESSING
                    or task.lease_owner != self.runtime.worker_id
                    or not task.has_valid_lease(
                        worker_id=self.runtime.worker_id,
                        now_utc=now,
                        attempt_count=attempt_count,
                        lease_generation=lease_generation,
                    )
                ):
                    return
                if retryable:
                    failed = await self.commit._retry_or_fail_task_in_transaction(
                        task,
                        error_code=error_code,
                        now=now,
                        correlation_id=correlation_id,
                        connection=connection,
                    )
                else:
                    failed = await self.commit._fail_task_in_transaction(
                        task,
                        error_code=error_code,
                        now=now,
                        correlation_id=correlation_id,
                        connection=connection,
                    )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "task.failure_persistence_failed",
                correlation_id=correlation_id,
                task_id=task_id,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
            )
            return
        if self.runtime.wakeup is not None:
            self.runtime.wakeup.set()
        log_event(
            logger,
            logging.WARNING if failed else logging.INFO,
            "task.failed" if failed else "task.retry_scheduled",
            correlation_id=correlation_id,
            task_id=task_id,
            error_code=error_code,
        )

    async def _heartbeat_lease(self, task: ConversationTask) -> None:
        async def renew() -> object | None:
            return await self.runtime.runtime_tasks.renew_lease(
                task.task_id,
                worker_id=self.runtime.worker_id,
                now_utc=self.runtime.clock(),
                lease_seconds=self.runtime.settings.lease_seconds,
                attempt_count=task.attempt_count,
                lease_generation=task.lease_generation,
            )

        await LeaseHeartbeat(
            renew,
            interval_seconds=self.runtime.settings.lease_heartbeat_interval_seconds,
        ).run()

    async def _run_agent_with_lease(
        self,
        task: ConversationTask,
        invocation: AgentInvocation,
    ) -> object:
        """Own the Agent and lease-heartbeat tasks for one Runtime attempt."""

        agent_task = asyncio.create_task(
            self.runtime.agent.run(invocation),
            name=f"echo-agent-{task.task_id}",
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat_lease(task),
            name=f"echo-lease-heartbeat-{task.task_id}",
        )
        try:
            done, _ = await asyncio.wait(
                (agent_task, heartbeat_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                try:
                    await heartbeat_task
                except LeaseLostError:
                    raise
                raise LeaseHeartbeatError("task lease heartbeat stopped unexpectedly")
            return await agent_task
        finally:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            if not agent_task.done():
                agent_task.cancel()
            await asyncio.gather(heartbeat_task, agent_task, return_exceptions=True)

    async def run_task(self, task_id: UUID) -> bool:
        """Run one claimed S2.5 Task; all writes happen before or after Agent I/O."""

        await self.runtime.ensure_started()
        task = await self.runtime.runtime_tasks.get(task_id)
        started_at = self.runtime.clock()
        if (
            task is None
            or task.status is not TaskStatus.PROCESSING
            or task.lease_owner != self.runtime.worker_id
        ):
            return False
        if not task.has_valid_lease(
            worker_id=self.runtime.worker_id,
            now_utc=started_at,
            attempt_count=task.attempt_count,
            lease_generation=task.lease_generation,
        ):
            log_event(
                logger,
                logging.INFO,
                "task.lease_expired_before_run",
                correlation_id=task.trace_id,
                task_id=task.task_id,
                worker_id=self.runtime.worker_id,
                attempt_count=task.attempt_count,
            )
            return True
        agent_started_at = perf_counter()
        agent_id = self.runtime.agent.agent_id
        route = resolve_agent_route(self.runtime.agent, "conversation.reply")
        allowed_tools = self._allowed_conversation_tools()
        await self.runtime._event(
            task.trace_id,
            "agent.started",
            "task",
            str(task.task_id),
            safe_trace_payload(
                "agent.started",
                attempt_count=task.attempt_count,
                agent_id=agent_id,
                task_kind=route.task_kind,
                requested_model_profile=route.requested_profile,
                model_profile=route.resolved_profile,
                route_fallback=route.fallback_reason,
            ),
        )
        log_event(
            logger,
            logging.INFO,
            "agent.call.started",
            correlation_id=task.trace_id,
            task_id=task.task_id,
            agent_id=agent_id,
            attempt_count=task.attempt_count,
        )
        try:
            async with self.runtime.database.transaction() as connection:
                context = await self.runtime.snapshot_builder.build(
                    task,
                    now_utc=started_at,
                    recent_limit=self.runtime.settings.recent_message_limit,
                    recent_max_chars=self.runtime.settings.recent_message_max_chars,
                    covered_overlap=self.runtime.settings.covered_message_overlap,
                    memory_search_max_results=self.runtime.settings.memory_search_max_results,
                    allow_memory_search=bool(allowed_tools),
                    connection=connection,
                )
            invocation = AgentInvocation(
                identity=InvocationIdentity(
                    agent_id=agent_id,
                    agent_kind=self.runtime.agent.agent_kind,
                    purpose=InvocationPurpose.CONVERSATION_REPLY,
                    attempt=task.attempt_count,
                ),
                scope=ConversationScope(
                    conversation_id=task.conversation_id,
                    character_id=task.character_id,
                ),
                context=context,
                context_input=ContextInputRef(
                    snapshot_id=context.context_version,
                    snapshot_schema_version=context.snapshot_version,
                    snapshot_fingerprint=context.input_fingerprint,
                ),
                output_contract=OutputContractRef(
                    kind="character_message",
                    version="v2",
                ),
                execution_policy=ExecutionPolicy(
                    allowed_tools=allowed_tools,
                    model_profile=route.resolved_profile,
                    harness_version=self.runtime.agent.harness_version,
                    max_model_steps=5 if allowed_tools else 1,
                    max_model_requests=5 if allowed_tools else 1,
                    max_tool_calls=4 if allowed_tools else 0,
                    max_output_tokens=self.runtime.settings.conversation_max_output_tokens,
                    temperature=self.runtime.settings.conversation_temperature,
                    top_p=self.runtime.settings.conversation_top_p,
                    deadline_utc=(
                        task.lease_until_utc
                        - timedelta(
                            seconds=max(
                                0.0,
                                self.runtime.settings.lease_safety_margin_seconds,
                            )
                        )
                        if task.lease_until_utc is not None
                        else None
                    ),
                ),
                correlation=Correlation(task_id=task.task_id, trace_id=task.trace_id),
            )
            raw_run_result = await self._run_agent_with_lease(task, invocation)
            if not isinstance(raw_run_result, AgentRunResult):
                try:
                    run_result = AgentRunResult.model_validate(raw_run_result)
                except ValidationError as exc:
                    raise InvalidAgentRunError("Agent Run result is invalid") from exc
            else:
                run_result = raw_run_result
            self.commit._validate_run_identity(run_result, invocation)
            await self.runtime._event(
                task.trace_id,
                "agent.completed",
                "task",
                str(task.task_id),
                safe_trace_payload(
                    "agent.completed",
                    agent_id=agent_id,
                    invocation_id=str(run_result.invocation_id),
                    baseline_resource_id=context.baseline_resource_id,
                    baseline_version=context.baseline_version,
                    harness_version=run_result.harness_version,
                    identity_resource_id=context.identity_resource_id,
                    identity_version=context.identity_version,
                    task_kind=route.task_kind,
                    requested_model_profile=route.requested_profile,
                    model_profile=run_result.model_profile,
                    route_fallback=route.fallback_reason,
                    output_schema=CHARACTER_MESSAGE_OUTPUT_SCHEMA,
                    prompt_layout_version=context.prompt_layout_version,
                    run_status=run_result.status.value,
                    stop_reason=run_result.stop_reason.value,
                    step_count=run_result.step_count,
                    model_request_count=run_result.usage_summary.model_request_count,
                    tool_call_count=run_result.usage_summary.tool_call_count,
                    input_tokens=run_result.usage_summary.input_tokens,
                    cache_read_tokens=run_result.usage_summary.cache_read_tokens,
                    cache_write_tokens=run_result.usage_summary.cache_write_tokens,
                    output_tokens=run_result.usage_summary.output_tokens,
                    total_tokens=run_result.usage_summary.total_tokens,
                    cache_hit_ratio=run_result.usage_summary.cache_hit_ratio,
                    repair_count=run_result.repair_count,
                ),
            )
            await self.runtime.record_agent_run_observations(
                invocation,
                run_result,
                entity_type="task",
                entity_id=str(task.task_id),
            )
            if run_result.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL}:
                decision = decide_agent_run(run_result)
                if decision is None:
                    raise InvalidAgentRunError("Agent Run did not provide a recovery decision")
                error_code = decision.failure.code
                await self.runtime._event(
                    task.trace_id,
                    "agent.failed",
                    "task",
                    str(task.task_id),
                    safe_trace_payload(
                        "agent.failed",
                        error_code=error_code,
                        attempt_count=task.attempt_count,
                    ),
                )
                await self._schedule_task_failure(
                    task.task_id,
                    task.trace_id,
                    error_code,
                    attempt_count=task.attempt_count,
                    lease_generation=task.lease_generation,
                    retryable=decision.action is RecoveryAction.RETRY_TASK,
                )
                return True
            proposal = self.commit._proposal_from_run(run_result, invocation)
        except LeaseLostError as exc:
            log_event(
                logger,
                logging.WARNING,
                "agent.call.lease_lost",
                correlation_id=task.trace_id,
                task_id=task.task_id,
                agent_id=agent_id,
                attempt_count=task.attempt_count,
                error_code=exc.code,
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(agent_started_at),
            )
            await self._schedule_task_failure(
                task.task_id,
                task.trace_id,
                exc.code,
                attempt_count=task.attempt_count,
                lease_generation=task.lease_generation,
            )
            return True
        except Exception as exc:
            error_code = self.runtime._error_code(exc)
            log_event(
                logger,
                logging.WARNING,
                "agent.call.failed",
                correlation_id=task.trace_id,
                task_id=task.task_id,
                agent_id=agent_id,
                attempt_count=task.attempt_count,
                error_code=error_code,
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(agent_started_at),
            )
            await self.runtime._event(
                task.trace_id,
                "agent.failed",
                "task",
                str(task.task_id),
                safe_trace_payload(
                    "agent.failed",
                    error_code=error_code,
                    attempt_count=task.attempt_count,
                ),
            )
            await self._schedule_task_failure(
                task.task_id,
                task.trace_id,
                error_code,
                attempt_count=task.attempt_count,
                lease_generation=task.lease_generation,
            )
            return True

        try:
            await self.commit.commit_task_result(
                task.task_id,
                invocation=invocation,
                run_result=run_result,
                proposal=proposal,
                lease_generation=task.lease_generation,
            )
        except Exception as exc:
            # Keep the durable processing lease intact.  A database failure is
            # recovered by the normal lease-expiry path instead of being
            # converted into a second, non-atomic state transition.
            log_event(
                logger,
                logging.ERROR,
                "task.commit_failed",
                correlation_id=task.trace_id,
                task_id=task.task_id,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(agent_started_at),
            )
        log_event(
            logger,
            logging.INFO,
            "agent.call.completed",
            correlation_id=task.trace_id,
            task_id=task.task_id,
            agent_id=agent_id,
            attempt_count=task.attempt_count,
            status=run_result.status.value,
            stop_reason=run_result.stop_reason.value,
            proposal_id=proposal.proposal_id if proposal else None,
            duration_ms=_duration_ms(agent_started_at),
        )
        return True


__all__ = ["ConversationExecutionService"]
