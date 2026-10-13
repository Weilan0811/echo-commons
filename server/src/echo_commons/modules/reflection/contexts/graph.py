import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from echo_commons.agents.contracts.context import EnvironmentContext, MemoryContext, MemoryItem
from echo_commons.agents.contracts.input import ActionSpace, ActorScope, SourceVersion
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.modules.perspective.contracts import ObservationScope, WorldReader
from echo_commons.modules.reflection.contracts.context import (
    MEMORY_NODE_CONTRACT,
    REFLECTION_NODE_CONTRACT,
    FactMaterial,
    GraphContextSnapshot,
    MessageMaterial,
    ReflectionMaterial,
)
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class ReflectionContextPolicy:
    allowed_tools: frozenset[str]
    resident_memory_limit: int
    max_materials: int
    max_material_chars: int


class GraphContext:
    def __init__(
        self,
        policy: ReflectionContextPolicy,
        characters: CharacterContext,
        communities: CommunityReader,
        conversations: ConversationReader,
        perspective: WorldReader,
        entries: MemoryEntryRepository,
        retrieval: MemoryRetrieval,
    ) -> None:
        self.policy, self.characters, self.communities = policy, characters, communities
        self.conversations, self.perspective = conversations, perspective
        self.entries, self.retrieval = entries, retrieval

    def prepare(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str | None,
        upper_sequence: int,
        graph_kind: ReflectionGraphKind,
        source_kind: Literal[
            "memory_segment", "memory_summary_batch", "author_material_batch", "memory_change_set"
        ],
        source_id: str,
        source_version: str,
        materials: tuple[ReflectionMaterial, ...],
        now: datetime,
    ) -> GraphContextSnapshot:
        community = self.communities.get(connection, community_id)
        conversation = (
            self.conversations.get(connection, community_id, conversation_id)
            if conversation_id
            else None
        )
        observation = (
            self.perspective.observe(
                connection,
                ObservationScope(
                    community_id,
                    conversation_id,
                    ActorRef("character", character_id),
                    upper_sequence,
                ),
            )
            if conversation_id
            else None
        )
        targets = (
            {participant.actor for participant in observation.participants}
            if observation
            else set()
        )
        targets.update(
            item.message.sender
            for item in materials
            if isinstance(item, MessageMaterial) and isinstance(item.message.sender, ActorRef)
        )
        character = self.characters.prepare(
            connection,
            community_id,
            character_id,
            frozenset(targets),
            now,
            self.policy.allowed_tools,
        )
        names = {
            (item.target.kind.value, item.target.actor_id): item.target_name
            for item in character.self_context.relationships
        }
        named_materials = []
        for material in materials:
            if isinstance(material, FactMaterial) and material.fact_kind == "relationship":
                content = json.loads(material.content)
                content.update(
                    observer_name=character.self_context.name,
                    target_name=names[(content["target_kind"], content["target_id"])],
                )
                material = material.model_copy(
                    update={"content": json.dumps(content, ensure_ascii=False)}
                )
            named_materials.append(material)
        materials = tuple(named_materials)
        if (
            len(materials) > self.policy.max_materials
            or sum(
                len(item.message.text) if isinstance(item, MessageMaterial) else len(item.content)
                for item in materials
            )
            > self.policy.max_material_chars
        ):
            raise ValueError("Reflection source materials exceed the configured limit")
        resident = tuple(
            MemoryItem(
                memory_id=row["memory_id"],
                content_version=row["content_version"],
                content=row["content"],
            )
            for row in self.entries.active_rows(
                connection,
                community_id,
                character_id,
                valid_at=now,
                recorded_before=now,
            )
            if row["visibility"] == "resident"
        )[: self.policy.resident_memory_limit]
        versions = (
            *character.source_versions,
            SourceVersion(
                kind="community", source_id=community_id, version=str(community.state_version)
            ),
            SourceVersion(
                kind="memory_search",
                source_id=character_id,
                version=self.retrieval.source_version(
                    connection,
                    SearchScope(
                        community_id,
                        character_id,
                        now,
                        conversation_id,
                        upper_sequence if conversation_id else None,
                    ),
                ),
            ),
            *(
                SourceVersion(kind=item.kind, source_id=item.source_id, version=item.version)
                for item in materials
            ),
            *(
                SourceVersion(
                    kind="memory_entry", source_id=item.memory_id, version=item.content_version
                )
                for item in resident
            ),
        )
        return GraphContextSnapshot(
            snapshot_id=str(uuid4()),
            prepared_at_utc=now,
            scope=ActorScope(community_id=community_id, character_id=character_id),
            graph_kind=graph_kind,
            source_kind=source_kind,
            source_id=source_id,
            source_version=source_version,
            conversation_id=conversation_id,
            observation_upper_sequence=upper_sequence,
            self=character.self_context,
            memory=MemoryContext(resident=resident),
            environment=EnvironmentContext(
                world_time_utc=community.world_time_utc,
                community_status=community.status.value,
                conversation_kind=conversation.kind.value if conversation else "direct",
            ),
            public_facts=tuple(
                f"{participant.actor.kind.value}:{participant.actor.actor_id} "
                f"{participant.display_name}"
                for participant in observation.participants
                if observation is not None
            )
            if observation
            else (),
            materials=tuple(materials),
            source_versions=versions,
            action_space=ActionSpace(
                output_contracts=(
                    MEMORY_NODE_CONTRACT
                    if graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE
                    else REFLECTION_NODE_CONTRACT,
                ),
                tools=character.self_context.capabilities,
            ),
        )
