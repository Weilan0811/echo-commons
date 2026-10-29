import asyncio
import json
from uuid import uuid4
from weakref import WeakValueDictionary

from echo_commons.agents.contracts.activity import PersonaProjection, PersonaText
from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.protocol import (
    ModelRequest,
    ModelResponseKind,
    PromptMessage,
)
from echo_commons.modules.activities.contracts import ActivityContextPolicy
from echo_commons.shared.errors import ConflictError


class ActivityPersona:
    def __init__(
        self,
        database: Database,
        model_budget: ModelBudget,
        model_profile: str,
        policy: ActivityContextPolicy,
    ) -> None:
        self.database, self.model_budget, self.model_profile, self.policy = (
            database,
            model_budget,
            model_profile,
            policy,
        )
        self._locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()

    def version(self, common: ContextSnapshot) -> str:
        return json.dumps(
            {
                "projection_contract": "v1",
                "max_chars": self.policy.persona_projection_max_chars,
                "sources": [
                    item.model_dump(mode="json")
                    for item in common.source_versions
                    if item.kind in ("blueprint", "identity_resource")
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    async def prepare(self, common: ContextSnapshot) -> PersonaProjection:
        identity = common.self
        text = PersonaText(
            profile=identity.profile,
            voice=identity.voice,
            relational_dynamics=identity.relational_dynamics,
        )
        version = self.version(common)
        if (
            sum(len(value) for value in text.model_dump().values())
            <= self.policy.persona_direct_max_chars
        ):
            return PersonaProjection(**text.model_dump(), source_version=version, mode="direct")
        lock = self._locks.setdefault((identity.blueprint_id, version), asyncio.Lock())
        async with lock:
            with self.database.read() as connection:
                row = connection.execute(
                    "SELECT projection_json FROM activity_persona_projections "
                    "WHERE blueprint_id=? AND source_version=?",
                    (identity.blueprint_id, version),
                ).fetchone()
            if row:
                return PersonaProjection.model_validate_json(row[0])
            request = ModelRequest(
                invocation_id=uuid4(),
                trace_id=uuid4(),
                agent_id=f"activity-persona:{identity.blueprint_id}",
                model_profile=self.model_profile,
                attempt=1,
                step_index=1,
                output_contract=OutputContractRef(kind="activity_persona", version="v1"),
                messages=(
                    PromptMessage(
                        role="system",
                        content=read_prompt_resource("activity/persona.md")
                        + f"\n三份正文合计最多 {self.policy.persona_projection_max_chars} 个字符。"
                        + "\n只返回符合此结构的 JSON：\n"
                        + json.dumps(PersonaText.model_json_schema(), ensure_ascii=False),
                    ),
                    PromptMessage(role="user", content=text.model_dump_json()),
                ),
                max_output_tokens=4096,
            )
            response = await self.model_budget.generate(request)
            if response.kind is not ModelResponseKind.TERMINAL:
                raise ConflictError("Persona projection did not produce a complete result")
            projected = PersonaText.model_validate(response.output)
            if (
                not all(value.strip() for value in projected.model_dump().values())
                or sum(len(value) for value in projected.model_dump().values())
                > self.policy.persona_projection_max_chars
            ):
                raise ConflictError(
                    "Persona projection exceeds its budget or omits required documents"
                )
            result = PersonaProjection(
                **projected.model_dump(), source_version=version, mode="model"
            )
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO activity_persona_projections VALUES (?,?,?,?,?) "
                    "ON CONFLICT(blueprint_id,source_version) DO NOTHING",
                    (
                        identity.blueprint_id,
                        version,
                        result.model_dump_json(),
                        request.model_dump_json(),
                        response.model_dump_json(),
                    ),
                )
            return result
