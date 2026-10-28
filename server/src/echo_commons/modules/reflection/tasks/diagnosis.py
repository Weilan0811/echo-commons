import asyncio
import json
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.execution import PreparedExecution
from echo_commons.agents.contracts.invocation import DraftFeedback
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import AgentRunStatus, AgentStep, UsageSummary
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.execution.clock import utc_now
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.models.protocol import (
    ModelGateway,
    ModelGatewayError,
    ModelRequest,
    ModelResponseKind,
    PromptMessage,
)
from echo_commons.modules.reflection.contracts.diagnosis import DiagnosisPolicy, DiagnosisReport
from echo_commons.modules.reflection.repositories.draft_steps import DraftStepRepository
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.modules.reflection.tasks.readiness import ReflectionInputReadiness

DIAGNOSIS_CONTRACT = OutputContractRef(kind="reflection_diagnosis", version="v1")


def diagnosis_messages(invocation, draft, outputs):
    original = project_node(
        invocation.context,
        output_contract=invocation.output_contract,
        outputs=outputs,
        max_content_chars=invocation.execution_policy.max_content_chars,
    )
    return (
        PromptMessage(role="system", content=read_prompt_resource("reflection/diagnosis.md")),
        PromptMessage(
            role="system",
            content="诊断 JSON Schema：\n"
            + json.dumps(DiagnosisReport.model_json_schema(), ensure_ascii=False),
        ),
        PromptMessage(
            role="user",
            content=json.dumps(
                {
                    "original_task_and_materials": [
                        m.model_dump(mode="json") for m in original.messages
                    ],
                    "output_limits": invocation.execution_policy.output_instructions,
                    "draft": draft,
                },
                ensure_ascii=False,
            ),
        ),
    )


class CandidateDiagnosis:
    def __init__(
        self,
        queue: ReflectionQueue,
        gateway: ModelGateway,
        outputs: OutputRegistry,
        readiness: ReflectionInputReadiness,
        policy: DiagnosisPolicy,
        profile: str,
    ):
        self.queue, self.gateway, self.outputs = queue, gateway, outputs
        self.readiness, self.policy, self.profile = readiness, policy, profile
        self.steps = DraftStepRepository()

    def enabled(self, invocation):
        return self.policy.enabled(invocation.context.node_kind)

    def _owned(self, connection, lease):
        if not self.queue.owned(connection, lease, utc_now()):
            raise LeaseLostError("Reflection diagnosis no longer owns its node")

    def _start(self, lease, revision, phase, invocation_id, request_json, **kwargs):
        with self.queue.database.transaction() as connection:
            self._owned(connection, lease)
            return self.steps.start(
                connection, lease, revision, phase, invocation_id, request_json, utc_now(), **kwargs
            )

    def _finish(self, lease, step_id, **kwargs):
        with self.queue.database.transaction() as connection:
            # 调用记录保留真实结果；租约失效仍会阻止后续调用与正式提交。
            self.steps.finish(connection, step_id, utc_now(), **kwargs)
        with self.queue.database.read() as connection:
            self._owned(connection, lease)

    def _load(self, lease, invocation):
        with self.queue.database.read() as connection:
            self._owned(connection, lease)
            writer = self.steps.latest_writer(connection, lease)
            if writer is None:
                return None, None, ()
            original = json.loads(writer["request_json"])
            if (
                original["execution_policy"]["repair_hint"]
                != invocation.execution_policy.repair_hint
                or original["execution_policy"]["model_profile"]
                != invocation.execution_policy.model_profile
            ):
                return None, None, ()
            report = self.steps.report(connection, writer["step_id"])
            history = tuple(
                DraftFeedback(
                    draft=json.loads(row["result_json"])["output"]["payload"],
                    feedback="整理诊断结果：\n"
                    + row["report_json"]
                    + "\n请根据问题修改完整草稿，仍按原任务结构返回。",
                )
                for row in self.steps.history(connection, lease)
            )
            return dict(writer), dict(report) if report else None, history

    async def run(self, lease, prepared: PreparedExecution):
        invocation = prepared.invocation
        writer, checked, history = await asyncio.to_thread(self._load, lease, invocation)
        revision = writer["revision"] if writer else 0
        result = self.outputs.restore_result(writer["result_json"]) if writer else None
        usage, steps, repairs, attempts = UsageSummary(), [], 0, 0
        while True:
            report = (
                DiagnosisReport.model_validate_json(checked["report_json"]) if checked else None
            )
            if report and report.passed:
                return result.model_copy(
                    update={
                        "invocation_id": invocation.identity.invocation_id,
                        "usage_summary": usage,
                        "steps": tuple(steps),
                        "repair_count": repairs,
                        "provider_attempt_count": attempts,
                    }
                )
            if report:
                if revision >= self.policy.max_revisions:
                    raise ExecutionError(
                        "reflection_diagnosis_revision_limit", FailureCategory.REVIEW
                    )
                revision += 1
                writer, checked = None, None
            if writer is None:
                current = invocation.model_copy(
                    update={
                        "identity": invocation.identity.model_copy(
                            update={"invocation_id": uuid4()}
                        ),
                        "execution_policy": invocation.execution_policy.model_copy(
                            update={"revision_history": history}
                        ),
                    }
                )
                writer_id = await asyncio.to_thread(
                    self._start,
                    lease,
                    revision,
                    "writer",
                    current.identity.invocation_id,
                    current.model_dump_json(),
                )
                start = perf_counter()
                result = await prepared.agent.run(current)
                await asyncio.to_thread(
                    self._finish,
                    lease,
                    writer_id,
                    result_json=result.model_dump_json(),
                    duration_ms=round((perf_counter() - start) * 1000),
                )
                usage = usage.add(result.usage_summary)
                offset = len(steps)
                steps.extend(
                    step.model_copy(update={"step_index": offset + n})
                    for n, step in enumerate(result.steps, 1)
                )
                repairs += result.repair_count
                attempts += result.provider_attempt_count or 0
                if result.status is not AgentRunStatus.COMPLETED or result.output is None:
                    return result.model_copy(
                        update={
                            "invocation_id": invocation.identity.invocation_id,
                            "usage_summary": usage,
                            "steps": tuple(steps),
                            "repair_count": repairs,
                            "provider_attempt_count": attempts,
                        }
                    )
                writer = {"step_id": writer_id}
            request = ModelRequest(
                invocation_id=uuid4(),
                trace_id=invocation.correlation.trace_id,
                agent_id=invocation.identity.agent_id,
                model_profile=self.profile,
                attempt=lease.attempt,
                step_index=1,
                max_provider_retries=0,
                output_contract=DIAGNOSIS_CONTRACT,
                allowed_tools=(),
                messages=diagnosis_messages(
                    invocation, result.output.payload.model_dump(mode="json"), self.outputs
                ),
                temperature=0,
                max_output_tokens=invocation.execution_policy.max_output_tokens,
                deadline_utc=invocation.execution_policy.deadline_utc,
            )
            diagnosis_id = await asyncio.to_thread(
                self._start,
                lease,
                revision,
                "diagnosis",
                request.invocation_id,
                request.model_dump_json(),
                draft_step_id=writer["step_id"],
            )
            start = perf_counter()
            response = None
            try:
                await self.readiness.check(invocation)
                remaining = (
                    (request.deadline_utc - utc_now()).total_seconds()
                    if request.deadline_utc
                    else None
                )
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("reflection diagnosis deadline exceeded")
                response = await asyncio.wait_for(
                    self.gateway.generate(
                        request, before_request=lambda: self.readiness.check(invocation)
                    ),
                    timeout=remaining,
                )
                if response.kind is not ModelResponseKind.TERMINAL:
                    raise ModelGatewayError(
                        code=response.error_code or "reflection_diagnosis_invalid", retryable=True
                    )
                report = DiagnosisReport.model_validate(response.output)
            except (ModelGatewayError, ValidationError, TimeoutError) as error:
                code = getattr(
                    error,
                    "code",
                    "reflection_diagnosis_invalid"
                    if isinstance(error, ValidationError)
                    else "deadline_exceeded",
                )
                await asyncio.to_thread(
                    self._finish,
                    lease,
                    diagnosis_id,
                    error_code=code,
                    result_json=response.model_dump_json() if response else None,
                    duration_ms=round((perf_counter() - start) * 1000),
                )
                if isinstance(error, ValidationError):
                    raise ModelGatewayError(code=code, retryable=True) from error
                if isinstance(error, TimeoutError):
                    raise ExecutionError(
                        "deadline_exceeded", FailureCategory.DEADLINE, RecoveryAction.RETRY_TASK
                    ) from error
                raise
            await asyncio.to_thread(
                self._finish,
                lease,
                diagnosis_id,
                result_json=response.model_dump_json(),
                report_json=report.model_dump_json(),
                duration_ms=round((perf_counter() - start) * 1000),
            )
            usage = usage.add(response.usage_summary.model_copy(update={"model_request_count": 1}))
            attempts += response.provider_attempt
            steps.append(
                AgentStep(
                    step_index=len(steps) + 1,
                    response_kind="diagnosis",
                    usage_summary=response.usage_summary,
                    duration_ms=round((perf_counter() - start) * 1000),
                )
            )
            checked = {"report_json": report.model_dump_json()}
            if not report.passed:
                history = (
                    *history,
                    DraftFeedback(
                        draft=result.output.payload.model_dump(mode="json"),
                        feedback="整理诊断结果：\n"
                        + report.model_dump_json()
                        + "\n请根据问题修改完整草稿，仍按原任务结构返回。",
                    ),
                )

    def approved(self, connection, lease, invocation, result):
        if not self.enabled(invocation):
            return True
        writer = self.steps.latest_writer(connection, lease)
        if writer is None or result.output is None:
            return False
        report = self.steps.report(connection, writer["step_id"])
        return (
            report is not None
            and DiagnosisReport.model_validate_json(report["report_json"]).passed
            and json.loads(writer["result_json"])["output"]["payload"]
            == result.output.payload.model_dump(mode="json")
        )
