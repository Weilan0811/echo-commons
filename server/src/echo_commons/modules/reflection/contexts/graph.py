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
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.modules.perspective.contracts import WorldReader
from echo_commons.modules.reflection.contracts.context import (
    FACT_REVIEW_NODE_CONTRACT,
    MEMORY_NODE_CONTRACT,
    REFLECTION_NODE_CONTRACT,
    VIEW_NODE_CONTRACT,
    FactMaterial,
    GraphContextSnapshot,
    MessageMaterial,
    ReflectionMaterial,
    SummaryTaskContext,
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
        records: LongTermMemoryRepository,
        retrieval: MemoryRetrieval,
    ) -> None:
        self.policy, self.characters, self.communities = policy, characters, communities
        self.conversations, self.perspective = conversations, perspective
        self.records, self.retrieval = records, retrieval

    def source_segments(self, connection, community, character, source_kind, source_id):
        provenance = MemoryProvenanceRepository(self.perspective.activities)
        segments = set()
        if source_kind == "memory_segment":
            segments.add(source_id)
        elif source_kind == "memory_summary_batch":
            batch = provenance.get_batch(connection, community, character, source_id)
            segments.update(ref.segment_id for ref in batch.sources)
            for identity in batch.previous_digest_ids:
                segments.update(provenance.digest_segments(connection, identity))
        return tuple(
            SegmentRepository().get(connection, community, character, identity)
            for identity in sorted(segments)
        )

    def activity_sessions(self, connection, community, character, source_kind, source_id, now):
        if self.perspective.activities is None:
            return ()
        periods = {}
        for segment in self.source_segments(
            connection, community, character, source_kind, source_id
        ):
            if segment.activity_participation_id:
                participation = segment.activity_participation_id
                end = min(now, segment.ended_at_utc)
                periods[participation] = max(periods.get(participation, end), end)
        return tuple(
            self.perspective.activities.session_context(
                connection, community, character, participation, end
            )
            for participation, end in sorted(periods.items())
        )

    def summary_task(self, connection, community, character, kind, source_kind, source_id, now):
        if kind not in (
            ReflectionGraphKind.SEGMENT_REFLECT,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
        ):
            return None
        segments = self.source_segments(connection, community, character, source_kind, source_id)
        periods = {}
        for segment in segments:
            if segment.activity_participation_id:
                identity = segment.activity_participation_id
                end = min(now, segment.ended_at_utc)
                periods[identity] = max(periods.get(identity, end), end)
        ranges = tuple(
            self.perspective.activities.experience_range(
                connection, community, character, identity, end, now
            )
            for identity, end in sorted(periods.items())
        )
        purpose = "segment" if kind is ReflectionGraphKind.SEGMENT_REFLECT else "continuity"
        if purpose == "continuity" and len(periods) == 1 and ranges[0].closed_at_utc is not None:
            provenance = MemoryProvenanceRepository(self.perspective.activities)
            if provenance.covers_activity_episode(
                connection, next(iter(periods)), {segment.segment_id for segment in segments}
            ):
                purpose = "complete_experience"
        return SummaryTaskContext(purpose=purpose, activity_ranges=ranges)

    def prepare(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        graph_kind: ReflectionGraphKind,
        source_kind: Literal[
            "memory_segment", "memory_summary_batch", "author_material_batch", "memory_change_set"
        ],
        source_id: str,
        source_version: str,
        materials: tuple[ReflectionMaterial, ...],
        now: datetime,
        *,
        conversations=None,
    ) -> GraphContextSnapshot:
        community = self.communities.get(connection, community_id)
        conversations = (
            conversations
            if conversations is not None
            else self.perspective.freeze(
                connection, community_id, ActorRef("character", character_id), now
            )
        )
        targets = set()
        targets.update(
            item.message.sender
            for item in materials
            if isinstance(item, MessageMaterial) and isinstance(item.message.sender, ActorRef)
        )
        targets.update(
            actor for item in materials if item.kind == "game_event" for actor in item.actors
        )
        character = self.characters.prepare(
            connection,
            community_id,
            character_id,
            frozenset(targets),
            now,
            self.policy.allowed_tools,
        )
        if graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            queries = tuple(
                dict.fromkeys(
                    item.message.text if isinstance(item, MessageMaterial) else item.content
                    for item in materials
                    if item.kind in ("message", "author_chunk", "thought", "game_event")
                )
            )
            existing = {
                row["memory_id"]: row
                for row in self.records.active_rows(
                    connection,
                    community_id,
                    character_id,
                    recorded_before=now,
                )
            }
            size = sum(
                len(item.message.text) if isinstance(item, MessageMaterial) else len(item.content)
                for item in materials
            )
            background = []
            scope = SearchScope(
                community_id,
                character_id,
                now,
                conversations=conversations,
            )
            hits = self.retrieval.related_records(connection, scope, queries, limit=8)
            rows = (
                *self.records.review_rows(connection, community_id, character_id, now),
                *(existing.get(hit.source_id) for hit in hits),
            )
            for row in rows:
                if row is None:
                    continue
                source_rows = MemoryProvenanceRepository(
                    self.perspective.activities
                ).record_sources(
                    connection,
                    community_id,
                    character_id,
                    row["record_kind"],
                    row["memory_id"],
                    row["version"],
                )
                content = json.dumps(
                    {
                        **row,
                        "original_sources": [
                            (source["source_kind"], source["source_id"], source["source_version"])
                            for source in source_rows
                        ],
                    },
                    ensure_ascii=False,
                )
                if (
                    len(materials) + len(background) + 1 > self.policy.max_materials
                    or size + len(content) > self.policy.max_material_chars
                ):
                    continue
                background.append(
                    FactMaterial(
                        source_id=row["memory_id"],
                        version=row["content_version"],
                        fact_kind=f"memory_{row['record_kind']}",
                        content=content,
                    )
                )
                size += len(content)
            materials = (*materials, *background)
        if (
            len(materials) > self.policy.max_materials
            or sum(
                len(item.message.text) if isinstance(item, MessageMaterial) else len(item.content)
                for item in materials
            )
            > self.policy.max_material_chars
        ):
            raise ValueError("Reflection source materials exceed the configured limit")
        # 来源容量按选中的正文计算，称呼取自已冻结的人物上下文。
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
        resident = tuple(
            MemoryItem(
                memory_id=row["memory_id"],
                content_version=row["content_version"],
                content=row["content"],
                source_kind="author_preload",
            )
            for row in InitializationRepository().resident_preloads(
                connection,
                community_id,
                character_id,
                recorded_before=now,
            )
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
                        conversations=conversations,
                    ),
                ),
            ),
            *(
                SourceVersion(kind=item.kind, source_id=item.source_id, version=item.version)
                for item in materials
            ),
            *(
                SourceVersion(
                    kind=item.source_kind, source_id=item.memory_id, version=item.content_version
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
            conversations=conversations,
            self=character.self_context,
            memory=MemoryContext(resident=resident),
            environment=EnvironmentContext(
                world_time_utc=community.world_time_utc,
                community_status=community.status.value,
                conversation_kind="experience",
                timezone=community.timezone,
                world_description=community.world_description,
                community_rules=community.community_rules,
                community_version=community.state_version,
            ),
            public_facts=(),
            activity_sessions=self.activity_sessions(
                connection, community_id, character_id, source_kind, source_id, now
            ),
            summary_task=self.summary_task(
                connection, community_id, character_id, graph_kind, source_kind, source_id, now
            ),
            materials=tuple(materials),
            source_versions=versions,
            action_space=ActionSpace(
                output_contracts=(
                    MEMORY_NODE_CONTRACT
                    if graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE
                    else VIEW_NODE_CONTRACT
                    if graph_kind is ReflectionGraphKind.VIEW_REFRESH
                    else REFLECTION_NODE_CONTRACT,
                )
                + (
                    (FACT_REVIEW_NODE_CONTRACT,)
                    if graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE
                    else ()
                ),
                tools=character.self_context.capabilities,
            ),
        )
