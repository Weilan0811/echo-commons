import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.execution.contracts import Disposition, ExecutionOutcome
from echo_commons.execution.lease import LeaseLostError, with_heartbeat
from echo_commons.infrastructure.models.decision_protocol import (
    ChoiceQuestion,
    DecisionControls,
    DecisionRequest,
    DecisionRoute,
)
from echo_commons.infrastructure.models.factory import decision_gateway
from echo_commons.infrastructure.models.protocol import (
    ModelGatewayError,
    ModelRequest,
    PromptMessage,
)
from echo_commons.infrastructure.models.willingness import (
    SCORING_INSTRUCTION,
    SCORING_VERSION,
    WillingnessOutput,
    recommended_threshold,
)
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.conversations.tasks.prompt import participation_material
from echo_commons.modules.memory.services.context import HistorySummaryRequired


def willingness_question():
    return ChoiceQuestion(
        instructions=(
            "作为当前角色，根据自己的人设、状态、记忆和截至此刻可见的聊天，判断现在是否愿意开口回应。"
            "判断实际回应动机，而不是能否安全地说一句。与自己兴趣、经历或关系有关的话题，"
            "即使没有点名，也可以产生回应意愿。材料未写某件事，不等于角色确实不知道；"
            "不要为当前判断编造事实。"
        ),
        criteria={
            "speak": "此刻有明确回应动机，或有一句话想说，现在回应自然。",
            "silent": "此刻没有足够动机回应，现在保持沉默自然。",
        },
        allow_none=False,
    )


class WillingnessJudgments:
    def __init__(self, database, models, settings, context, tasks, gateway, decisions, review):
        self.database, self.models, self.settings = database, models, settings
        self.context, self.tasks, self.gateway, self.decisions, self.review = (
            context,
            tasks,
            gateway,
            decisions,
            review,
        )
        self.queue = None
        self._owned_decisions = False

    async def close(self):
        if self._owned_decisions:
            await self.decisions.close()

    def configuration(self):
        local = self.settings.mode == "local_willingness"
        entry = self.models.resolve(
            self.models.decision.profile
            if local
            else self.models.route_for("conversation_reply").resolved_profile,
            None if local else self.settings.remote_entry_id,
        )
        thinking = entry.model_vendor == "minimax" and entry.model.startswith("MiniMax-M3")
        if not local:
            thinking = (
                thinking
                or entry.extra_body.get("enable_thinking") is True
                or (entry.extra_body.get("thinking", {}).get("type") in {"enabled", "adaptive"})
            )
        frozen = entry.configuration()
        threshold = self.settings.threshold
        return {
            "mode": self.settings.mode,
            "model": frozen,
            "protocol": SCORING_VERSION,
            "threshold": threshold
            if threshold is not None
            else recommended_threshold(entry.model, local=local, thinking=thinking),
            "temperature": self.settings.temperature,
            "controls": self.models.decision.controls.model_copy(
                update={"none_check": False, "allow_none": False}
            ).model_dump(),
            "input_max_chars": self.models.decision.input_max_chars,
            "balance": self.settings.balance.model_dump(),
        }

    def add_batch(self, connection, turn):
        configuration = self.configuration()
        connection.execute(
            "INSERT INTO social_willingness_batches(social_turn_id,mode,configuration_json) "
            "VALUES (?,?,?)",
            (turn.social_turn_id, configuration["mode"], json.dumps(configuration)),
        )

    def add_candidate(self, connection, turn, member, inputs, at):
        try:
            snapshot = self.context.prepare(connection, turn, member, inputs, at)
        except HistorySummaryRequired as error:
            snapshot = error.snapshot
        except ContextBudgetExceeded:
            raise
        task_id = self.tasks.prepare(connection, snapshot)
        connection.execute(
            "INSERT INTO social_willingness_tasks(task_id,social_turn_id) VALUES (?,?)",
            (task_id, turn.social_turn_id),
        )
        return task_id

    def _load(self, lease):
        with self.database.read() as connection:
            row = self.queue.repository.owned(connection, lease, datetime.now(UTC))
            if row is None:
                raise LeaseLostError("Willingness task lease is no longer owned")
            snapshot = self.tasks.snapshot(connection, lease.task_id)
            if code := self.review.context(connection, snapshot):
                raise ModelGatewayError(code=code, retryable=False)
            judgment = connection.execute(
                "SELECT j.*,b.mode,b.configuration_json FROM social_willingness_tasks j "
                "JOIN social_willingness_batches b USING(social_turn_id) WHERE j.task_id=?",
                (lease.task_id,),
            ).fetchone()
            return snapshot, dict(judgment), row["trace_id"]

    def _request(self, snapshot, row, trace):
        config = json.loads(row["configuration_json"])
        material, question = participation_material(snapshot), willingness_question()
        if row["mode"] == "local_willingness":
            model = config["model"]
            route = DecisionRoute(
                entry_id=model["entry_id"],
                model_vendor=model["model_vendor"],
                model=model["model"],
                base_url=model["base_url"],
                credential_ref=model["credential_ref"],
                access_route=model["access_route"],
                request_timeout_seconds=model["request_timeout_seconds"],
                retry_backoff_seconds=model["retry_backoff_seconds"],
                input_max_chars=config["input_max_chars"],
                context_window_tokens=model["context_window_tokens"],
                output_tokens=model["max_output_tokens"],
                token_counter=model["token_counter"],
            )
            return self.decisions.prepare(
                DecisionRequest(
                    invocation_id=uuid4(),
                    trace_id=UUID(trace),
                    agent_id=f"character:{snapshot.scope.character_id}",
                    state=material,
                    model_profile="decision",
                    model_entry_id=model["entry_id"],
                    route=route,
                    controls=DecisionControls.model_validate(config["controls"]),
                    max_provider_retries=model["max_retries"],
                    questions={"participation": question},
                )
            ).model_copy(update={"deadline_utc": None})
        return ModelRequest(
            invocation_id=uuid4(),
            trace_id=UUID(trace),
            agent_id=f"character:{snapshot.scope.character_id}",
            model_profile="light",
            model_entry_id=config["model"]["entry_id"],
            model_configuration=config["model"],
            attempt=1,
            step_index=1,
            max_output_tokens=4096,
            response_schema=WillingnessOutput.model_json_schema(),
            output_contract=OutputContractRef(kind="social_willingness", version="v1"),
            messages=(
                PromptMessage(role="system", content=SCORING_INSTRUCTION),
                PromptMessage(
                    role="user",
                    content=json.dumps(material, ensure_ascii=False)
                    + "\n\nQuestion: "
                    + question.instructions
                    + "\nOptions:\n"
                    + "\n".join(f"{key}: {value}" for key, value in question.criteria.items()),
                ),
            ),
        )

    def _freeze_request(self, lease, request):
        with self.database.transaction() as connection:
            if self.queue.repository.owned(connection, lease, datetime.now(UTC)) is None:
                raise LeaseLostError()
            connection.execute(
                "UPDATE social_willingness_tasks SET request_json=? WHERE task_id=? "
                "AND request_json IS NULL",
                (request.model_dump_json(), lease.task_id),
            )

    async def execute(self, lease):
        return await with_heartbeat(
            self.queue, lease, self._execute(lease), self.queue.policy.lease_seconds / 3
        )

    async def _execute(self, lease):
        snapshot, row, trace = await asyncio.to_thread(self._load, lease)
        local = row["mode"] == "local_willingness"
        if local and self.decisions is None:
            self.decisions = decision_gateway(self.models, self.gateway)
            self._owned_decisions = True
        request_type = DecisionRequest if local else ModelRequest
        if row["request_json"]:
            request = request_type.model_validate_json(row["request_json"])
        else:
            request = self._request(snapshot, row, trace)
            await asyncio.to_thread(self._freeze_request, lease, request)
        request = request.model_copy(
            update={"attempt": lease.attempt, "deadline_utc": lease.expires_at_utc}
        )

        async def before_request():
            await asyncio.to_thread(self._load, lease)

        response = await (
            self.decisions.decide(request, before_request=before_request)
            if local
            else self.gateway.generate(request, before_request=before_request)
        )
        if local:
            answer = response.answers["participation"]
            score, choice = answer.probabilities["speak"], answer.choice
        else:
            try:
                parsed = WillingnessOutput.model_validate(response.output)
            except ValidationError as error:
                raise ModelGatewayError(
                    code="invalid_willingness_output", retryable=True
                ) from error
            score, choice = parsed.willingness_score, parsed.choice
        result = {
            "score": score,
            "choice": choice,
            "score_source": "option_probability" if local else "self_rating",
            "model": response.model,
            "latency_ms": response.latency_ms,
            "usage": response.usage_summary.model_dump(),
            "provider_attempt": response.provider_attempt,
        }
        await asyncio.to_thread(self._save, lease, result)
        return ExecutionOutcome(Disposition.COMPLETED)

    def _save(self, lease, result):
        with self.database.transaction() as connection:
            if self.queue.repository.owned(connection, lease, datetime.now(UTC)) is None:
                raise LeaseLostError()
            connection.execute(
                "UPDATE social_willingness_tasks SET result_json=? WHERE task_id=?",
                (json.dumps(result), lease.task_id),
            )
            self.queue.repository.release(
                connection, lease.task_id, "completed", datetime.now(UTC), datetime.now(UTC), None
            )

    def expression_selected(self, task_id):
        # 表达阶段只消费social已经安排的结果，不再调用判断模型。

        with self.database.read() as connection:
            row = connection.execute(
                "SELECT expression_selected FROM social_willingness_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return bool(row and row[0])
