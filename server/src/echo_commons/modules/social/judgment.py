import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.models.decision import DecisionGateway
from echo_commons.infrastructure.models.decision_protocol import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResponse,
)
from echo_commons.infrastructure.models.protocol import ModelGatewayError


@dataclass(frozen=True, slots=True)
class ParticipationVerdict:
    choice: str = "ordinary"
    usage: UsageSummary = UsageSummary()
    duration_ms: int = 0
    model_profile: str = ""
    reused: bool = False


def participation_question():
    return ChoiceQuestion(
        instructions=read_prompt_resource("social/participation.md"),
        criteria={
            "participate": "我已有值得说的内容，想在此刻开口。",
            "silent": "我现在愿意听着，没有需要补充的话。",
            "understand": "我需要进一步理解眼前语境，再决定是否开口。",
        },
        allow_none=False,
    )


class SocialParticipation:
    def __init__(
        self,
        database: Database,
        gateway: DecisionGateway | None,
        material: Callable[[ContextSnapshot], dict[str, object]],
        owned: Callable,
        check_context: Callable,
    ):
        self.database, self.gateway, self.material = database, gateway, material
        self.owned, self.check_context = owned, check_context

    def freeze(self, connection, task_id: str, snapshot: ContextSnapshot) -> None:
        kind = connection.execute(
            "SELECT kind FROM conversations WHERE conversation_id=?",
            (snapshot.scope.conversation_id,),
        ).fetchone()[0]
        request, timeout = None, 30
        if self.gateway is not None and kind == "group" and not snapshot.scope.initiation_id:
            trace = connection.execute(
                "SELECT trace_id FROM conversation_tasks WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            request = self.gateway.prepare(
                DecisionRequest(
                    invocation_id=uuid4(),
                    trace_id=UUID(trace),
                    agent_id=f"character:{snapshot.scope.community_id}:{snapshot.scope.character_id}",
                    state=self.material(snapshot)
                    if snapshot.memory.retrieval_prepared and snapshot.memory.context_prepared
                    else None,
                    questions={"participation": participation_question()},
                )
            ).model_copy(update={"deadline_utc": None})
            timeout = self.gateway.registry.decision.timeout_seconds
        connection.execute(
            "INSERT INTO social_participation_judgments(task_id,mode,request_json,timeout_seconds) "
            "VALUES (?,?,?,?) ON CONFLICT(task_id) DO NOTHING",
            (
                task_id,
                "decision" if request else "ordinary",
                request.model_dump_json() if request else None,
                timeout,
            ),
        )

    def _check(self, connection, lease, snapshot):
        if self.owned(connection, lease, datetime.now(UTC)) is None:
            raise LeaseLostError("Participation task lease is no longer owned")
        if code := self.check_context(connection, snapshot):
            raise ExecutionError(code, FailureCategory.SOURCE)

    def _load(self, lease, snapshot):
        with self.database.read() as connection:
            self._check(connection, lease, snapshot)
            row = connection.execute(
                "SELECT * FROM social_participation_judgments WHERE task_id=?", (lease.task_id,)
            ).fetchone()
            return dict(row) if row else None

    def _save(self, lease, snapshot, response: DecisionResponse):
        with self.database.transaction() as connection:
            self._check(connection, lease, snapshot)
            connection.execute(
                "UPDATE social_participation_judgments "
                "SET choice=?,response_json=?,decided_at_utc=? "
                "WHERE task_id=? AND choice IS NULL",
                (
                    response.answers["participation"].choice,
                    response.model_dump_json(),
                    utc_text(datetime.now(UTC)),
                    lease.task_id,
                ),
            )

    def _prepare_material(self, lease, snapshot, request):
        with self.database.transaction() as connection:
            self._check(connection, lease, snapshot)
            connection.execute(
                "UPDATE social_participation_judgments SET request_json=? WHERE task_id=? "
                "AND json_extract(request_json,'$.state') IS NULL AND choice IS NULL",
                (request.model_dump_json(), lease.task_id),
            )

    async def evaluate(self, lease: TaskLease, snapshot: ContextSnapshot) -> ParticipationVerdict:
        row = await asyncio.to_thread(self._load, lease, snapshot)
        if row is None or row["mode"] == "ordinary":
            return ParticipationVerdict()
        request = DecisionRequest.model_validate_json(row["request_json"])
        if row["response_json"] is not None:
            return ParticipationVerdict(
                choice=row["choice"], model_profile=request.model_profile, reused=True
            )
        if self.gateway is None:
            raise ModelGatewayError(code="provider_not_configured", retryable=False)
        if request.state is None:
            # 自动检索完成后再固定模型材料，路由和开关仍沿用原计划。
            request = request.model_copy(update={"state": self.material(snapshot)})
            await asyncio.to_thread(self._prepare_material, lease, snapshot, request)
        request = request.model_copy(
            update={
                "attempt": lease.attempt,
                "deadline_utc": min(
                    lease.expires_at_utc,
                    datetime.now(UTC) + timedelta(seconds=row["timeout_seconds"]),
                ),
            }
        )

        async def before_request():
            await asyncio.to_thread(self._load, lease, snapshot)

        response = await self.gateway.decide(request, before_request=before_request)
        await asyncio.to_thread(self._save, lease, snapshot, response)
        return ParticipationVerdict(
            response.answers["participation"].choice,
            response.usage_summary,
            response.latency_ms,
            request.model_profile,
        )
