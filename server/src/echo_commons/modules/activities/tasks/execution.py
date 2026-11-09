import asyncio
import json
from datetime import timedelta
from uuid import UUID

from echo_commons.agents.contracts.activity import (
    ACTIVITY_REPLY_CONTRACT,
    ACTIVITY_REPLY_SELECTION_CONTRACT,
    ActivityReplySelection,
    ActivitySelection,
    selection_contract,
    turn_contract,
)
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.execution import ExecutionLimits
from echo_commons.agents.contracts.invocation import (
    AgentInvocation,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    InvocationScope,
)
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.refs import ContextInputRef
from echo_commons.agents.contracts.run import (
    AgentOutput,
    AgentRunResult,
    AgentRunStatus,
    AgentStep,
    AgentStopReason,
)
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import decide_run
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.decision import DecisionGateway
from echo_commons.infrastructure.models.decision_protocol import (
    DecisionRequest,
    DecisionResponse,
)
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.modules.activities.context import ActivityContext
from echo_commons.modules.activities.decisions import (
    build_decision,
    handoff_reasons,
    selection_goal,
)
from echo_commons.modules.activities.repositories.tasks import ActivityTasks
from echo_commons.modules.activities.tasks.prompt import (
    decision_material,
    decision_questions,
    understanding_instructions,
)
from echo_commons.modules.activities.tasks.readiness import ActivityReadiness
from echo_commons.modules.activities.tasks.recovery import REVIEW_HINT
from echo_commons.modules.activities.tasks.review import ActivityReview
from echo_commons.modules.characters.services.registry import AgentRegistry


class ActivityExecution:
    def __init__(
        self,
        database: Database,
        tasks: ActivityTasks,
        context: ActivityContext,
        agents: AgentRegistry,
        outputs: OutputRegistry,
        decisions: DecisionGateway | None,
        readiness: ActivityReadiness,
        review: ActivityReview,
        limits: ExecutionLimits,
        recorder: ExecutionRecorder,
    ) -> None:
        self.database, self.tasks, self.context, self.agents, self.outputs = (
            database,
            tasks,
            context,
            agents,
            outputs,
        )
        self.decisions, self.readiness, self.review, self.limits, self.recorder = (
            decisions,
            readiness,
            review,
            limits,
            recorder,
        )

    def _load(self, lease):
        with self.database.read() as connection:
            return dict(self.readiness.check_in(connection, lease))

    def _stage(self, lease, column, data):
        with self.database.transaction() as connection:
            self.readiness.check_in(connection, lease)
            self.tasks.save_stage(connection, lease, column, data, utc_now())

    def _save_decision(self, lease, request, response):
        with self.database.transaction() as connection:
            self.readiness.check_in(connection, lease)
            now = utc_now()
            self.tasks.save_stage(
                connection, lease, "decision_response_json", response.model_dump_json(), now
            )
            self.recorder.record(
                connection,
                lease,
                "run_finished",
                ExecutionEventPayload(
                    reason_code="local_decision",
                    observation=ExecutionObservation(
                        usage_summary=response.usage_summary,
                        provider_attempt_count=response.provider_attempt,
                    ),
                ),
                now,
                str(request.invocation_id),
            )

    async def execute(self, lease: TaskLease) -> dict:
        row = await asyncio.to_thread(self._load, lease)
        if row["prepared_json"]:
            return json.loads(row["prepared_json"])
        if row["mode"] == "automatic":
            artifact = {
                "mode": "automatic",
                "run": None,
                "invocation": None,
                "decision_request": None,
                "decision_response": None,
            }
            artifact["decision"] = build_decision(row, artifact).model_dump(mode="json")
            await asyncio.to_thread(
                self._stage, lease, "prepared_json", json.dumps(artifact, ensure_ascii=False)
            )
            return artifact
        reply = row["purpose"] == "reply"
        prepare = self.context.prepare_reply if reply else self.context.prepare_turn
        snapshot = await prepare(
            row["community_id"],
            row["character_id"],
            row["game_id"],
            input_id=row["input_id"],
            participation_id=row["participation_id"],
        )
        if not reply and (
            snapshot.opportunity.opportunity_id != row["opportunity_id"]
            or snapshot.material.game.state_version != row["state_version"]
        ):
            raise ExecutionError(
                "opportunity_replaced", FailureCategory.SOURCE, RecoveryAction.IGNORE
            )
        ordinary = row["mode"] == "ordinary"
        request = response = None
        if not ordinary:
            request = DecisionRequest.model_validate_json(row["decision_request_json"])
            if request.state is None:
                questions = decision_questions(snapshot)
                request = request.model_copy(
                    update={"state": decision_material(snapshot), "questions": questions}
                )
                await asyncio.to_thread(
                    self._stage, lease, "decision_request_json", request.model_dump_json()
                )
            if row["decision_response_json"]:
                response = DecisionResponse.model_validate_json(row["decision_response_json"])
            else:
                if self.decisions is None:
                    raise ModelGatewayError(code="provider_not_configured", retryable=False)
                request_for_call = request.model_copy(
                    update={
                        "attempt": lease.attempt,
                        "deadline_utc": min(
                            lease.expires_at_utc,
                            utc_now() + timedelta(seconds=request.route.request_timeout_seconds),
                        ),
                    }
                )

                async def before_request():
                    await asyncio.to_thread(self._load, lease)

                response = await self.decisions.decide(
                    request_for_call, before_request=before_request
                )
                await asyncio.to_thread(self._save_decision, lease, request, response)
            ordinary = bool(handoff_reasons(response))
        if ordinary:
            saved = (
                self.outputs.restore_result(row["last_run_json"]) if row["last_run_json"] else None
            )
            with self.database.read() as connection:
                recovery = self.recorder.repository.latest(
                    connection, "activity_reply" if reply else "activity_turn", lease.task_id
                )
            rejected = recovery and recovery.decision.failure.category == FailureCategory.REVIEW
            if (
                saved
                and saved.status == AgentRunStatus.COMPLETED
                and saved.output is not None
                and not rejected
            ):
                invocation = AgentInvocation.model_validate(
                    {
                        **json.loads(row["last_invocation_json"]),
                        "context": snapshot,
                    }
                )
                result = saved
            else:
                invocation, agent = await asyncio.to_thread(self.invocation, lease, row, snapshot)
                await asyncio.to_thread(self.recorder.started, lease, invocation, utc_now())
                await asyncio.to_thread(
                    self._stage, lease, "last_invocation_json", invocation.model_dump_json()
                )
                result = await agent.run(invocation)
                await asyncio.to_thread(self.recorder.finished, lease, result, utc_now())
                if response:
                    result = result.model_copy(
                        update={
                            "usage_summary": response.usage_summary.add(result.usage_summary),
                            "provider_attempt_count": response.provider_attempt
                            + (result.provider_attempt_count or 0),
                            "steps": (
                                AgentStep(
                                    step_index=1,
                                    response_kind="decision",
                                    usage_summary=response.usage_summary,
                                    duration_ms=response.latency_ms,
                                ),
                                *(
                                    step.model_copy(update={"step_index": step.step_index + 1})
                                    for step in result.steps
                                ),
                            ),
                        }
                    )
                await asyncio.to_thread(
                    self._stage, lease, "last_run_json", result.model_dump_json()
                )
            recovery = decide_run(result)
            if recovery:
                raise ExecutionError(
                    recovery.failure.code, recovery.failure.category, recovery.action
                )
            if result.status != AgentRunStatus.COMPLETED or result.output is None:
                raise ExecutionError(
                    "activity_action_required", FailureCategory.REVIEW, RecoveryAction.RETRY_TASK
                )
            self.review.proposal(row, result.output.payload, snapshot)
            mode = "decision_then_ordinary" if response else "ordinary"
        else:
            question = "participation" if reply else "expression"
            goal = selection_goal(
                snapshot, request.questions[question], response.answers[question].choice
            )
            arguments = dict(
                retained_intent_ids=tuple(
                    i.intent_id
                    for index, i in enumerate(snapshot.material.working_memory.intents)
                    if response.answers[f"intent_{index}"].choice == "keep"
                ),
                expression_needed=goal is not None,
                expression_goal=goal,
            )
            if reply:
                proposal = ActivityReplySelection(**arguments)
            else:
                selected = next(
                    c
                    for c in snapshot.analysis.candidates
                    if c.candidate_id == response.answers["action"].choice
                )
                analyzer = self.context.gameplay.resolve(
                    snapshot.material.game.game_type,
                    snapshot.material.game.ruleset_id,
                    snapshot.material.game.ruleset_version,
                )
                proposal = ActivitySelection[analyzer.action_model](
                    action=selected.action, **arguments
                )
            invocation = None
            result = AgentRunResult(
                invocation_id=request.invocation_id,
                agent_id=request.agent_id,
                agent_kind="character",
                model_profile=request.model_profile,
                status=AgentRunStatus.COMPLETED,
                stop_reason=AgentStopReason.PROPOSAL_READY,
                output=AgentOutput(
                    contract=ACTIVITY_REPLY_SELECTION_CONTRACT
                    if reply
                    else selection_contract(snapshot.material.game.game_type),
                    payload=proposal,
                ),
                usage_summary=response.usage_summary,
                provider_attempt_count=response.provider_attempt,
                steps=(
                    AgentStep(
                        step_index=1,
                        response_kind="decision",
                        usage_summary=response.usage_summary,
                        duration_ms=response.latency_ms,
                    ),
                ),
            )
            await asyncio.to_thread(self._stage, lease, "last_run_json", result.model_dump_json())
            mode = "decision"
        artifact = {
            "mode": mode,
            "run": result.model_dump(mode="json"),
            "invocation": invocation.model_dump(mode="json") if invocation else None,
            "decision_request": request.model_dump(mode="json") if request else None,
            "decision_response": response.model_dump(mode="json") if response else None,
        }
        artifact["decision"] = build_decision(
            row, artifact, snapshot, result.output.payload
        ).model_dump(mode="json")
        await asyncio.to_thread(
            self._stage, lease, "prepared_json", json.dumps(artifact, ensure_ascii=False)
        )
        return artifact

    def invocation(self, lease, row, snapshot):
        reply = row["purpose"] == "reply"
        purpose = InvocationPurpose.ACTIVITY_REPLY if reply else InvocationPurpose.ACTIVITY_TURN
        with self.database.read() as connection:
            self.readiness.check_in(connection, lease)
            agent = self.agents.resolve(
                connection,
                row["community_id"],
                row["character_id"],
                purpose=purpose,
            )
            applied = self.recorder.repository.latest(connection, purpose.value, lease.task_id)
            hint = (
                REVIEW_HINT
                if applied and applied.decision.failure.category is FailureCategory.REVIEW
                else None
            )
        invocation = AgentInvocation(
            identity=InvocationIdentity(
                agent_id=agent.descriptor.agent_id,
                purpose=purpose,
                attempt=lease.attempt,
            ),
            scope=InvocationScope(
                community_id=row["community_id"],
                character_id=row["character_id"],
                task_id=lease.task_id,
                source_kind="activity_sources" if reply else "game_opportunity",
                source_id=row["task_id"] if reply else row["opportunity_id"],
            ),
            context=snapshot,
            context_input=ContextInputRef(
                snapshot_id=snapshot.snapshot_id, snapshot_schema_version=snapshot.schema_version
            ),
            output_contract=ACTIVITY_REPLY_CONTRACT
            if reply
            else turn_contract(snapshot.material.game.game_type),
            execution_policy=ExecutionPolicy(
                allowed_tools=snapshot.action_space.tools,
                model_profile=row["model_profile"],
                max_model_steps=self.limits.model_steps,
                max_model_requests=self.limits.model_requests,
                max_tool_calls=self.limits.tool_calls,
                max_output_tokens=self.limits.max_output_tokens,
                max_input_chars=self.context.policy.input_max_chars,
                temperature=self.limits.temperature,
                top_p=self.limits.top_p,
                deadline_utc=lease.expires_at_utc,
                output_instructions=understanding_instructions(snapshot),
                repair_hint=hint,
            ),
            correlation=Correlation(task_id=lease.task_id, trace_id=UUID(row["trace_id"])),
        )
        return invocation, agent
