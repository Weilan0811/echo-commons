from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter

from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationPurpose
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory, FailureInfo, RecoveryAction
from echo_commons.agents.contracts.run import (
    AgentRunResult,
    AgentRunStatus,
    AgentStep,
    AgentStopReason,
    RepairObservation,
    ToolActivity,
    UsageSummary,
)
from echo_commons.agents.harness.context import InputProjector, InputReadiness
from echo_commons.agents.harness.output import ModelOutputError, parse_terminal_output
from echo_commons.agents.harness.policy import HarnessPolicy
from echo_commons.agents.harness.progress import ProgressObservation
from echo_commons.agents.harness.recovery import (
    classify_gateway_error,
    classify_model_output_error,
    classify_tool_error,
)
from echo_commons.agents.harness.state import AgentRunState
from echo_commons.agents.harness.tools import (
    ToolAuthorizationError,
    ToolExecutionError,
    ToolRegistry,
    ToolResult,
)
from echo_commons.infrastructure.models.protocol import (
    ModelGateway,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelResponseKind,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentLoop:
    """Drive model → tool → observation until a terminal run state."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        outputs: OutputRegistry,
        projector: InputProjector,
        input_readiness: InputReadiness | None = None,
        tools: ToolRegistry | None = None,
        policy: HarnessPolicy | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.gateway = gateway
        self.outputs = outputs
        self.projector = projector
        self.input_readiness = input_readiness
        self.tools = tools or ToolRegistry()
        self.policy = policy or HarnessPolicy()
        self.clock = clock

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        state = AgentRunState(
            invocation,
            self.projector(
                invocation.context,
                output_contract=invocation.output_contract,
                outputs=self.outputs,
                tool_definitions=self.tools.definitions(invocation.execution_policy.allowed_tools),
            ),
        )
        if invocation.execution_policy.output_instructions:
            state.prompt_context = state.prompt_context.with_user_instruction(
                invocation.execution_policy.output_instructions
            )
        if invocation.execution_policy.repair_hint:
            state.prompt_context = state.prompt_context.with_user_instruction(
                invocation.execution_policy.repair_hint
            )
        step_limit = self.policy.model_step_limit(invocation)
        request_limit = self.policy.model_request_limit(invocation)
        tool_limit = self.policy.tool_call_limit(invocation)

        while True:
            if self._deadline_expired(invocation):
                failure = self._deadline_failure()
                return self._result(
                    state,
                    AgentRunStatus.RETRYABLE,
                    AgentStopReason.DEADLINE_EXCEEDED,
                    (failure.code,),
                    recovery=failure,
                )
            if state.step_count >= step_limit:
                failure = self._budget_failure("model_step_budget_exhausted")
                return self._result(
                    state,
                    AgentRunStatus.FAILED,
                    AgentStopReason.BUDGET_EXHAUSTED,
                    (failure.code,),
                    recovery=failure,
                )
            if state.model_request_count >= request_limit:
                failure = self._budget_failure("model_request_budget_exhausted")
                return self._result(
                    state,
                    AgentRunStatus.FAILED,
                    AgentStopReason.BUDGET_EXHAUSTED,
                    (failure.code,),
                    recovery=failure,
                )

            allowed_tools = state.control.enabled_tools(invocation.execution_policy.allowed_tools)
            state.prompt_context = state.prompt_context.with_tool_definitions(
                self.tools.definitions(allowed_tools)
            )
            step_started_at = perf_counter()
            request = ModelRequest(
                invocation_id=invocation.identity.invocation_id,
                trace_id=invocation.correlation.trace_id,
                agent_id=invocation.identity.agent_id,
                model_profile=invocation.execution_policy.model_profile,
                max_provider_retries=0
                if invocation.identity.purpose is InvocationPurpose.REFLECTION
                else None,
                attempt=invocation.identity.attempt,
                step_index=state.step_count + 1,
                messages=state.prompt_context.messages,
                output_contract=invocation.output_contract,
                allowed_tools=allowed_tools,
                tool_definitions=state.prompt_context.tool_definitions,
                remaining_tool_calls=max(0, tool_limit - state.tool_call_count),
                max_output_tokens=invocation.execution_policy.max_output_tokens,
                temperature=invocation.execution_policy.temperature,
                top_p=invocation.execution_policy.top_p,
                deadline_utc=invocation.execution_policy.deadline_utc,
            )
            state.add_usage(UsageSummary(model_request_count=1))
            try:
                response = await self._generate(request, invocation)
            except asyncio.CancelledError:
                raise
            except ModelGatewayError as exc:
                if state.provider_attempt_count is not None:
                    state.provider_attempt_count += exc.provider_attempt
                failure = classify_gateway_error(exc)
                status = (
                    AgentRunStatus.RETRYABLE
                    if failure.action is RecoveryAction.RETRY_TASK
                    else AgentRunStatus.FAILED
                )
                return self._result(
                    state,
                    status,
                    AgentStopReason.MODEL_ERROR,
                    (failure.code,),
                    recovery=failure,
                )
            except TimeoutError:
                state.provider_attempt_count = None
                failure = self._deadline_failure()
                return self._result(
                    state,
                    AgentRunStatus.RETRYABLE,
                    AgentStopReason.DEADLINE_EXCEEDED,
                    (failure.code,),
                    recovery=failure,
                )
            if state.provider_attempt_count is not None:
                state.provider_attempt_count += response.provider_attempt
            state.add_usage(
                response.usage_summary.model_copy(
                    update={"model_request_count": 0, "tool_call_count": 0}
                )
            )
            if response.kind is ModelResponseKind.TERMINAL:
                try:
                    output = parse_terminal_output(response, invocation, self.outputs)
                except ModelOutputError as exc:
                    self._add_step(
                        state,
                        response,
                        step_started_at,
                        diagnostic_codes=(exc.code,),
                    )
                    failure = self._model_output_failure(state, exc.code)
                    if failure.action is RecoveryAction.REPAIR:
                        self._append_repair(state, response, failure)
                        continue
                    return self._result(
                        state,
                        AgentRunStatus.FAILED,
                        AgentStopReason.INVALID_MODEL_OUTPUT,
                        (failure.code,),
                        recovery=failure,
                    )
                state.output = output
                self._add_step(state, response, step_started_at)
                return self._result(
                    state,
                    AgentRunStatus.COMPLETED,
                    AgentStopReason.PROPOSAL_READY,
                )
            if response.kind is ModelResponseKind.NO_PROPOSAL:
                self._add_step(state, response, step_started_at)
                return self._result(
                    state,
                    AgentRunStatus.NO_PROPOSAL,
                    AgentStopReason.NO_MOTIVATION,
                )
            if response.kind is ModelResponseKind.INVALID:
                error_code = response.error_code or "invalid_model_output"
                self._add_step(
                    state,
                    response,
                    step_started_at,
                    diagnostic_codes=(error_code,),
                )
                failure = self._model_output_failure(state, error_code)
                if failure.action is RecoveryAction.REPAIR:
                    self._append_repair(state, response, failure)
                    continue
                return self._result(
                    state,
                    AgentRunStatus.FAILED,
                    AgentStopReason.INVALID_MODEL_OUTPUT,
                    (failure.code,),
                    recovery=failure,
                )

            state.prompt_context = state.prompt_context.with_tool_calls(response.tool_calls)
            activities: list[ToolActivity] = []
            diagnostic_codes: list[str] = []
            repair_hints: list[str] = []
            pending_repairs: list[RepairObservation] = []
            progress_instructions: dict[str, str] = {}
            failure: FailureInfo | None = None
            stop_reason = AgentStopReason.TOOL_ERROR

            for call in response.tool_calls:
                if call.name not in allowed_tools or not self.tools.has(call.name):
                    activity = ToolActivity(
                        call_id=call.call_id,
                        name=call.name,
                        ok=False,
                        error_code="tool_not_allowed",
                        duration_ms=0,
                    )
                    activities.append(activity)
                    diagnostic_codes.append("tool_not_allowed")
                    failure = classify_tool_error("tool_not_allowed", repair_allowed=False)
                    stop_reason = AgentStopReason.TOOL_NOT_ALLOWED
                    break
                if state.tool_call_count >= tool_limit:
                    activities.append(
                        ToolActivity(
                            call_id=call.call_id,
                            name=call.name,
                            ok=False,
                            error_code="tool_budget_exhausted",
                            duration_ms=0,
                        )
                    )
                    diagnostic_codes.append("tool_budget_exhausted")
                    failure = classify_tool_error("tool_budget_exhausted", repair_allowed=False)
                    stop_reason = AgentStopReason.BUDGET_EXHAUSTED
                    break

                tool_started_at = perf_counter()
                try:
                    result = await self.tools.execute(call, invocation)
                except ToolAuthorizationError as exc:
                    activities.append(
                        ToolActivity(
                            call_id=call.call_id,
                            name=call.name,
                            ok=False,
                            error_code=exc.code,
                            duration_ms=_duration_ms(tool_started_at),
                        )
                    )
                    diagnostic_codes.append(exc.code)
                    failure = classify_tool_error(exc.code, repair_allowed=False)
                    stop_reason = AgentStopReason.TOOL_NOT_ALLOWED
                    break
                except ToolExecutionError as exc:
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        ok=False,
                        error_code=exc.code,
                    )
                state.add_usage(UsageSummary(tool_call_count=1))
                progress = self._observe_progress(state, call.name, result)
                activities.append(
                    ToolActivity(
                        call_id=call.call_id,
                        name=call.name,
                        ok=result.ok,
                        error_code=result.error_code,
                        duration_ms=_duration_ms(tool_started_at),
                        progressed=progress.progressed if progress is not None else None,
                        new_item_count=progress.new_item_count if progress is not None else 0,
                        no_progress_streak=(
                            progress.no_progress_streak if progress is not None else None
                        ),
                    )
                )
                state.prompt_context = state.prompt_context.with_observation(
                    tool_name=call.name,
                    call_id=call.call_id,
                    ok=result.ok,
                    output=result.output,
                    error_code=result.error_code,
                    progressed=progress.progressed if progress is not None else None,
                    new_item_count=progress.new_item_count if progress is not None else 0,
                    no_progress_streak=(
                        progress.no_progress_streak if progress is not None else None
                    ),
                )

                if not result.ok:
                    error_code = result.error_code or "tool_error"
                    diagnostic_codes.append(error_code)
                    tool_failure = self._tool_failure(state, error_code)
                    if tool_failure.action is RecoveryAction.REPAIR:
                        repair_hints.append(f"错误码：{error_code}。{tool_failure.repair_hint}")
                        pending_repairs.append(
                            RepairObservation(
                                code=error_code,
                                category=tool_failure.category,
                                hint=tool_failure.repair_hint,
                                step_index=state.step_count + 1,
                            )
                        )
                        continue
                    failure = tool_failure
                    stop_reason = (
                        AgentStopReason.BUDGET_EXHAUSTED
                        if error_code == "tool_budget_exhausted"
                        else AgentStopReason.TOOL_ERROR
                    )
                    break

                if progress is None or progress.progressed:
                    progress_instructions.pop(call.name, None)
                    continue
                registration = self.tools.registration(call.name)
                limit = (
                    registration.no_progress_limit
                    if registration is not None and registration.no_progress_limit is not None
                    else self.policy.max_no_progress_streak
                )
                if progress.no_progress_streak >= limit:
                    state.control.disable_tool(call.name)
                    progress_instructions[call.name] = (
                        f"工具 {call.name} 已连续多次没有提供新材料。本次运行不会再提供该工具，"
                        "请根据现有材料回答。"
                    )
                else:
                    progress_instructions[call.name] = (
                        f"工具 {call.name} 本次没有提供新材料，可以改变查询方式，"
                        "也可以根据现有材料直接回答。"
                    )

            self._add_step(
                state,
                response,
                step_started_at,
                activities=activities,
                diagnostic_codes=tuple(diagnostic_codes),
            )
            if failure is not None:
                status = (
                    AgentRunStatus.RETRYABLE
                    if failure.action is RecoveryAction.RETRY_TASK
                    else AgentRunStatus.FAILED
                )
                return self._result(
                    state,
                    status,
                    stop_reason,
                    (failure.code,),
                    recovery=failure,
                )
            if repair_hints:
                state.repair_observations.extend(pending_repairs)
                state.prompt_context = state.prompt_context.with_user_instruction(
                    "工具参数需要修正。" + "；".join(repair_hints)
                )
            if progress_instructions:
                state.prompt_context = state.prompt_context.with_user_instruction(
                    "\n".join(progress_instructions.values())
                )

    async def _generate(self, request: ModelRequest, invocation: AgentInvocation) -> ModelResponse:
        before_request = (
            (lambda: self.input_readiness.check(invocation))
            if self.input_readiness is not None
            else None
        )
        if invocation.execution_policy.deadline_utc is None:
            return await self.gateway.generate(request, before_request=before_request)
        remaining = (invocation.execution_policy.deadline_utc - self.clock()).total_seconds()
        if remaining <= 0:
            raise TimeoutError("agent invocation deadline exceeded")
        return await asyncio.wait_for(
            self.gateway.generate(request, before_request=before_request), timeout=remaining
        )

    def _deadline_expired(self, invocation: AgentInvocation) -> bool:
        deadline = invocation.execution_policy.deadline_utc
        return deadline is not None and deadline <= self.clock()

    def _observe_progress(
        self,
        state: AgentRunState,
        tool_name: str,
        result: ToolResult,
    ) -> ProgressObservation | None:
        registration = self.tools.registration(tool_name)
        if registration is None or registration.progress_extractor is None or not result.ok:
            return None
        keys = registration.progress_extractor(result)
        return state.control.progress_for(tool_name).observe(keys)

    def _model_output_failure(self, state: AgentRunState, error_code: str) -> FailureInfo:
        repair_allowed = (
            state.control.repair_counts.get(error_code, 0) < self.policy.max_repairs_per_error
        )
        failure = classify_model_output_error(error_code, repair_allowed=repair_allowed)
        if failure.action is RecoveryAction.REPAIR:
            state.control.record_repair(error_code)
        return failure

    def _tool_failure(self, state: AgentRunState, error_code: str) -> FailureInfo:
        repair_allowed = (
            state.control.repair_counts.get(error_code, 0) < self.policy.max_repairs_per_error
        )
        failure = classify_tool_error(error_code, repair_allowed=repair_allowed)
        if failure.action is RecoveryAction.REPAIR:
            state.control.record_repair(error_code)
        return failure

    @staticmethod
    def _append_repair(
        state: AgentRunState,
        response: ModelResponse,
        failure: FailureInfo,
    ) -> None:
        hint = failure.repair_hint or "请重新生成符合输出要求的内容。"
        state.repair_observations.append(
            RepairObservation(
                code=failure.code,
                category=failure.category,
                hint=hint,
                step_index=state.step_count,
            )
        )
        if response.output is not None:
            state.prompt_context = state.prompt_context.with_assistant_output(response.output)
        state.prompt_context = state.prompt_context.with_repair_instruction(
            failure.code,
            hint,
        )

    @staticmethod
    def _deadline_failure() -> FailureInfo:
        return FailureInfo(
            code="deadline_exceeded",
            category=FailureCategory.DEADLINE,
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
        )

    @staticmethod
    def _budget_failure(code: str) -> FailureInfo:
        return FailureInfo(
            code=code,
            category=FailureCategory.BUDGET,
            action=RecoveryAction.FAIL,
        )

    @staticmethod
    def _add_step(
        state: AgentRunState,
        response: ModelResponse,
        started_at: float,
        *,
        activities: list[ToolActivity] | None = None,
        diagnostic_codes: tuple[str, ...] = (),
    ) -> None:
        state.add_step(
            AgentStep(
                step_index=state.step_count + 1,
                response_kind=response.kind.value,
                tool_activities=tuple(activities or ()),
                usage_summary=response.usage_summary,
                duration_ms=_duration_ms(started_at),
                diagnostic_codes=diagnostic_codes,
            )
        )

    @staticmethod
    def _result(
        state: AgentRunState,
        status: AgentRunStatus,
        stop_reason: AgentStopReason,
        diagnostic_codes: tuple[str, ...] = (),
        *,
        recovery: FailureInfo | None = None,
    ) -> AgentRunResult:
        invocation = state.invocation
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            agent_kind=invocation.identity.agent_kind,
            harness_version=invocation.execution_policy.harness_version,
            model_profile=invocation.execution_policy.model_profile,
            status=status,
            stop_reason=stop_reason,
            steps=tuple(state.steps),
            output=state.output,
            usage_summary=state.usage_summary,
            repair_count=state.control.repair_count,
            diagnostic_codes=diagnostic_codes,
            recovery=recovery,
            provider_attempt_count=state.provider_attempt_count,
            repair_observations=tuple(state.repair_observations),
        )


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
