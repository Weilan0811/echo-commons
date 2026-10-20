import json
import logging
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from uuid import UUID, uuid4

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.infrastructure.models.protocol import (
    ModelRequest,
    ModelResponseKind,
    PromptMessage,
)
from echo_commons.modules.characters.domain.people import RelationshipSeeds
from echo_commons.modules.characters.domain.relationship import (
    RelationshipEvidence,
    RelationshipKey,
    RelationshipState,
    RelationshipValues,
)
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.services.facts import reflection_relationship_policy
from echo_commons.modules.memory.contracts import MemoryChangeWriter
from echo_commons.modules.memory.repositories.initialization import InitializationRepository

logger = logging.getLogger("echo_commons.characters.initialization")


def validate_seeds(output, material):
    seeds = RelationshipSeeds.model_validate(output)
    entries = {item["relationship_id"]: item for item in material["relationships"]}
    if len(seeds.relationships) != len(entries) or {
        str(item.relationship_id) for item in seeds.relationships
    } != set(entries):
        raise ValueError("Initial relationships must match the confirmed material IDs")
    for seed in seeds.relationships:
        text = entries[str(seed.relationship_id)]["content"]
        if not seed.evidence_quote.strip() or (
            seed.support_quote and not seed.support_quote.strip()
        ):
            raise ValueError("Relationship evidence quotes must be nonempty text")
        if seed.evidence_quote not in text or (
            seed.support_quote and seed.support_quote not in text
        ):
            raise ValueError("Relationship evidence must quote the confirmed relationship text")
    return seeds


def apply_pending_relationships(connection, community, now, changes: MemoryChangeWriter):
    repository = RelationshipRepository()
    policy = reflection_relationship_policy()
    rows = connection.execute(
        "SELECT i.*,c.community_id,c.blueprint_version FROM memory_initializations i "
        "JOIN character_instances c USING(character_id) "
        "WHERE c.community_id=? AND i.relationship_output_json IS NOT NULL",
        (community,),
    ).fetchall()
    for row in rows:
        material = json.loads(row["relationship_input_json"])
        entries = {
            item["relationship_id"]: (index, item)
            for index, item in enumerate(material["relationships"])
        }
        seeds = validate_seeds(json.loads(row["relationship_output_json"]), material)
        for seed in seeds.relationships:
            if not seed.acquaintance:
                continue
            index, entry = entries[str(seed.relationship_id)]
            target = connection.execute(
                "SELECT * FROM character_person_bindings WHERE community_id=? AND person_id=?",
                (community, entry["target_person_id"]),
            ).fetchone()
            if target is None or (target["actor_kind"], target["actor_id"]) == (
                "character",
                row["character_id"],
            ):
                continue
            key = RelationshipKey(
                community, row["character_id"], target["actor_kind"], target["actor_id"]
            )
            source = f"{row['character_id']}:relationship:{index}"
            if repository.evidence(connection, key, "author_relationship", source):
                continue
            evidence = RelationshipEvidence(
                uuid4(),
                key,
                "support" if seed.support_quote else "interaction",
                "author_relationship",
                source,
                now,
                now,
            )
            repository.add_evidence(
                connection,
                evidence,
                sources=(("author_material", source, row["blueprint_version"]),),
            )
            changes.record(
                connection,
                community,
                row["character_id"],
                "relationship",
                f"{row['character_id']}/{key.target_kind.value}/{key.target_id}",
                f"initialization:{evidence.evidence_id}",
                now,
            )
            # 已有社群经历继续决定当前关系，初始材料不能重置这些结果。
            current = repository.get(connection, key, now)
            if current.state_version:
                continue
            friend = (
                evidence.evidence_kind in policy.friend_qualifying_kinds
                and seed.affection >= policy.friend_minimum_affection
                and seed.trust >= policy.friend_minimum_trust
            )
            repository.save(
                connection,
                RelationshipState(
                    key,
                    "friend" if friend else "acquaintance",
                    RelationshipValues(seed.affection, seed.trust, seed.attachment),
                    1,
                    now,
                    evidence.evidence_id if friend else None,
                    seed.attitude,
                    (evidence.evidence_id,),
                ),
            )


class CharacterRelationshipInitialization:
    def __init__(self, database, budget, routing, changes: MemoryChangeWriter):
        self.database, self.budget, self.routing = database, budget, routing
        self.changes = changes
        self.repository = InitializationRepository()
        self.prompt = (
            files("echo_commons")
            .joinpath("resources/authoring/initialize-relationships.md")
            .read_text(encoding="utf-8")
            + "\n"
            + json.dumps(RelationshipSeeds.model_json_schema(), ensure_ascii=False)
        )

    def prepare(self, connection, character, content):
        if not content.relationships:
            return
        frozen = dict(
            relationships=[item.model_dump(mode="json") for item in content.relationships],
            profile=self.routing.route_for("character_authoring").resolved_profile,
            prompt=self.prompt,
            invocation_id=str(uuid4()),
            name=content.display_name,
        )
        connection.execute(
            "UPDATE memory_initializations SET phase='relationships',relationship_input_json=? "
            "WHERE character_id=?",
            (json.dumps(frozen, ensure_ascii=False), character),
        )

    async def run_once(self):
        with self.database.read() as connection:
            rows = self.repository.pending(connection, "relationships")
        if not rows:
            return False
        row = rows[0]
        material = json.loads(row["relationship_input_json"])
        try:
            # 已写入的结果在恢复时直接复用，模型调用不占用数据库写事务。
            if row["relationship_output_json"]:
                seeds = validate_seeds(json.loads(row["relationship_output_json"]), material)
            else:
                messages = (
                    PromptMessage(role="system", content=material["prompt"]),
                    PromptMessage(
                        role="user",
                        content=json.dumps(
                            dict(name=material["name"], relationships=material["relationships"]),
                            ensure_ascii=False,
                        ),
                    ),
                )
                response = await self.budget.generate(
                    ModelRequest(
                        invocation_id=UUID(material["invocation_id"]),
                        trace_id=uuid4(),
                        agent_id=f"initialization:{row['character_id']}",
                        model_profile=material["profile"],
                        attempt=row["attempts"] + 1,
                        step_index=1,
                        messages=messages,
                        max_output_tokens=8000,
                        output_contract=OutputContractRef(
                            kind="character_relationship_initialization", version="1.0"
                        ),
                        deadline_utc=datetime.now(UTC) + timedelta(seconds=180),
                    )
                )
                if response.kind != ModelResponseKind.TERMINAL:
                    raise ValueError("Relationship initialization requires a terminal response")
                seeds = validate_seeds(response.output, material)
            now = datetime.now(UTC)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE memory_initializations SET relationship_output_json=? "
                    "WHERE character_id=? AND phase='relationships'",
                    (seeds.model_dump_json(), row["character_id"]),
                )
            with self.database.transaction() as connection:
                self.apply(connection, row["community_id"], now)
                self.repository.advance(connection, row["character_id"], "materials", now)
        except Exception:
            logger.exception("Character relationship initialization failed")
            with self.database.transaction() as connection:
                self.repository.fail(
                    connection,
                    row["character_id"],
                    "relationship_initialization_failed",
                    datetime.now(UTC),
                )
        return True

    def apply(self, connection, community, now):
        apply_pending_relationships(connection, community, now, self.changes)
