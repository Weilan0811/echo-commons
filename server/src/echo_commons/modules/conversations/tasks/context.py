from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.context import (
    ContextSnapshot,
    ConversationSummary,
    EnvironmentContext,
    HistoricalThought,
    MemoryContext,
    MemoryItem,
    ObservedMessage,
    PerspectiveContext,
    SnapshotScope,
)
from echo_commons.agents.contracts.input import ActionSpace, SourceVersion
from echo_commons.agents.contracts.output import CHARACTER_EXPRESSION_CONTRACT
from echo_commons.infrastructure.models.budget import InputBudget
from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.blueprints import BlueprintReader
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.tasks.memory import budget_snapshot
from echo_commons.modules.memory.domain.policy import ContextMemoryPolicy
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.modules.memory.services.views import MemoryViews
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.social.domain import SocialTurn
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    recent_message_limit: int
    recent_message_max_chars: int
    resident_memory_limit: int
    allowed_tools: frozenset[str]
    covered_message_overlap: int
    automatic_memory_limit: int = 5
    automatic_memory_max_chars: int = 4000
    input_max_chars: int = 32000

    def __post_init__(self) -> None:
        if (
            min(
                self.recent_message_limit, self.recent_message_max_chars, self.resident_memory_limit
            )
            < 1
        ):
            raise ValueError("Context material limits must be positive")
        if self.covered_message_overlap < 0:
            raise ValueError("Covered message overlap must be nonnegative")
        if self.automatic_memory_limit < 1 or self.automatic_memory_max_chars < 1:
            raise ValueError("Automatic memory limits must be positive")


class ConversationContext:
    def __init__(
        self,
        policy: ContextPolicy,
        catalog: BlueprintCatalog | BlueprintReader,
        communities: CommunityRepository,
        conversations: ConversationRepository,
        instances: InstanceRepository,
        states: StateRepository,
        relationships: RelationshipRepository,
        authors: InitializationRepository,
        provenance: MemoryProvenanceRepository,
        perspective: WorldPerspective,
        retrieval: MemoryRetrieval,
        capabilities: CapabilityResolver,
    ) -> None:
        self.policy, self.communities, self.conversations = (
            policy,
            communities,
            conversations,
        )
        self.authors, self.provenance, self.perspective, self.retrieval = (
            authors,
            provenance,
            perspective,
            retrieval,
        )

        self.character_context = CharacterContext(
            catalog, instances, states, relationships, perspective, capabilities
        )
        self.input_budget: InputBudget | None = None
        self.memory_policy = ContextMemoryPolicy()

    def prepare(
        self,
        connection: sqlite3.Connection,
        turn: SocialTurn,
        member: Membership,
        inputs: tuple[Message, ...],
        now: datetime,
        *,
        situation: str = "",
    ) -> ContextSnapshot:
        return self.prepare_for(
            connection,
            SnapshotScope(
                community_id=turn.community_id,
                character_id=member.actor.actor_id,
                conversation_id=turn.conversation_id,
                membership_id=member.membership_id,
                observation_upper_sequence=turn.observation_max_sequence,
                social_turn_id=turn.social_turn_id,
                **({"initiation_id": turn.initiation_id} if turn.initiation_id else {}),
            ),
            member,
            inputs,
            now,
            membership_version=turn.membership_version,
            situation=situation,
        )

    def prepare_for(
        self,
        connection: sqlite3.Connection,
        scope: SnapshotScope,
        member: Membership,
        inputs: tuple[Message, ...],
        now: datetime,
        *,
        membership_version: int,
        situation: str = "",
        apply_budget: bool = True,
        trigger_message_ids: tuple[str, ...] | None = None,
        current_membership_only: bool = False,
    ) -> ContextSnapshot:
        input_budget = self.input_budget if apply_budget else None
        trigger_ids = (
            tuple(message.message_id for message in inputs)
            if trigger_message_ids is None
            else trigger_message_ids
        )
        inputs = tuple(
            sorted(
                {message.message_id: message for message in inputs}.values(),
                key=lambda message: message.sequence,
            )
        )
        character_id = member.actor.actor_id
        instance = self.character_context.instances.get(
            connection, scope.community_id, character_id
        )
        instance.require_ready()
        views = (
            MemoryViews().read(connection, scope.community_id, character_id)
            if instance.memory_mode is MemoryMode.FULL
            else ()
        )
        view_content = {row["view_kind"]: row["content"] for row in views}
        community = self.communities.get(connection, scope.community_id)
        conversation = self.conversations.get(connection, scope.community_id, scope.conversation_id)
        observation = self.perspective.observe(
            connection,
            ObservationScope(
                scope.community_id,
                scope.conversation_id,
                member.actor,
                scope.observation_upper_sequence,
                scope.membership_id if current_membership_only else None,
            ),
        )
        boundaries = self.perspective.freeze(
            connection,
            scope.community_id,
            member.actor,
            now,
            conversation_id=scope.conversation_id,
            upper_sequence=scope.observation_upper_sequence,
        )
        if current_membership_only:
            boundaries = tuple(
                boundary.model_copy(update={"membership_ids": (scope.membership_id,)})
                if boundary.conversation_id == scope.conversation_id
                else boundary
                for boundary in boundaries
            )
        visible = self.perspective.experiences(
            connection, scope.community_id, member.actor, boundaries, now
        )
        if input_budget is not None:
            reply_ids = {m.reply_to_message_id for m in inputs if m.reply_to_message_id}
            inputs = tuple(
                sorted(
                    {
                        m.message_id: m
                        for m in (*inputs, *(m for m in visible if m.message_id in reply_ids))
                    }.values(),
                    key=lambda m: m.sequence,
                )
            )
        input_ids = {message.message_id for message in inputs}
        first_input_sequence = min(
            (
                item.sequence
                for item in inputs
                if input_budget is None or item.message_id in trigger_ids
            ),
            default=scope.observation_upper_sequence + 1,
        )
        continuity_ids = frozenset(
            message.message_id
            for message in visible
            if message.conversation_id != scope.conversation_id
            or message.sequence < first_input_sequence
        )
        eligible = self.provenance.eligible_segments(
            connection, scope.community_id, character_id, continuity_ids, now
        )
        digests = self.provenance.latest_digests(
            connection,
            scope.community_id,
            character_id,
            recorded_before=now,
            eligible_segment_ids=frozenset(row["segment_id"] for row in eligible),
        )
        covered_segments = set().union(
            *(self.provenance.digest_segments(connection, row["digest_id"]) for row in digests)
        )
        summaries, summary_chars = [], 0
        for row in self.provenance.context_summaries(
            connection,
            scope.community_id,
            character_id,
            eligible,
            covered_segments,
            now,
            limit=None if input_budget is not None else 8,
        ):
            if input_budget is None and summary_chars + len(row["summary_text"]) > 8000:
                continue
            segment = SegmentRepository().get(
                connection, scope.community_id, character_id, row["segment_id"]
            )
            summaries.append(
                ConversationSummary(
                    segment_id=segment.segment_id,
                    content_version=segment.summary_version,
                    content=segment.summary_text,
                    started_at_utc=segment.started_at_utc,
                    ended_at_utc=segment.ended_at_utc,
                    conversations=segment.conversations,
                )
            )
            summary_chars += len(row["summary_text"])
        summaries.reverse()
        covered = SegmentRepository().covered(
            connection,
            scope.community_id,
            character_id,
            (
                {r["segment_id"] for r in eligible if r["status"] == "ingested"}
                if input_budget is not None
                else covered_segments | {summary.segment_id for summary in summaries}
            ),
        )
        thoughts = ThoughtRepository().for_results(
            connection,
            scope.community_id,
            character_id,
            tuple(
                message.result_id
                for message in visible
                if message.sender == member.actor and message.result_id
            ),
            now,
        )
        candidates = [message for message in visible if message.message_id not in input_ids]
        current = [
            message
            for message in reversed(candidates)
            if message.conversation_id == scope.conversation_id
        ]
        other = [
            message
            for message in reversed(candidates)
            if message.conversation_id != scope.conversation_id
        ]
        query = "\n".join((situation, *(message.text for message in inputs)))[-256:]
        search_scope = SearchScope(
            scope.community_id,
            character_id,
            now,
            scope.conversation_id,
            scope.observation_upper_sequence,
            conversations=boundaries,
        )
        relevant_ids = (
            {
                hit.source_id
                for hit in self.retrieval.search(
                    connection, search_scope, query, limit=self.policy.automatic_memory_limit
                )
                if hit.source_kind == "message"
            }
            if other and query.strip()
            else set()
        )
        other.sort(key=lambda message: message.message_id not in relevant_ids)
        first_count = max(1, self.policy.recent_message_limit // 2) if other else len(current)
        priorities = current[:first_count] + other + current[first_count:]
        history, history_thoughts = [], []
        remaining = self.policy.recent_message_max_chars
        overlaps = {}
        for message in priorities:
            if input_budget is None and len(history) >= self.policy.recent_message_limit:
                break
            if message.message_id in covered:
                count = overlaps.get(message.conversation_id, 0)
                if count >= self.policy.covered_message_overlap:
                    continue
                overlaps[message.conversation_id] = count + 1
            thought = thoughts.get(message.result_id)
            size = len(message.text) + (len(thought["content"]) if thought else 0)
            if input_budget is None and size > remaining:
                continue
            history.append(message)
            remaining -= size
            if thought:
                history_thoughts.append(
                    HistoricalThought(
                        message_id=message.message_id,
                        thought_id=thought["thought_id"],
                        content_version=thought["content_version"],
                        content=thought["content"],
                    )
                )
        history.sort(key=lambda message: (message.created_at_utc, message.message_id))
        targets = {participant.actor for participant in observation.participants}
        targets.update(
            message.sender
            for message in inputs + tuple(history)
            if isinstance(message.sender, ActorRef)
        )
        character = self.character_context.prepare(
            connection,
            scope.community_id,
            character_id,
            frozenset(targets),
            now,
            self.policy.allowed_tools,
        )
        resident = tuple(
            MemoryItem(
                memory_id=row["memory_id"],
                content_version=row["content_version"],
                content=row["content"],
                source_kind="author_preload",
            )
            for row in self.authors.resident_preloads(
                connection, scope.community_id, character_id, recorded_before=now
            )
        )[: self.policy.resident_memory_limit]
        tools = character.self_context.capabilities
        search_scope = SearchScope(
            scope.community_id,
            character_id,
            now,
            scope.conversation_id,
            scope.observation_upper_sequence,
            conversations=boundaries,
        )
        query = "\n".join((situation, *(message.text for message in inputs)))[-256:]
        if len(query) < 40 and any(
            word in query for word in ("那件", "那个", "之前", "后来", "他", "她")
        ):
            query = ("\n".join(message.text for message in history[-2:]) + "\n" + query)[-256:]
        recalled = []
        existing_text = {item.content for item in resident}
        existing_text.update(item.content for item in summaries)
        existing_text.update(message.text for message in inputs + tuple(history))
        if query.strip().strip("。！!？?，, ") not in {
            "你好",
            "嗨",
            "嗯",
            "好的",
            "好",
            "谢谢",
            "哈哈",
        }:
            hits = self.retrieval.search(
                connection, search_scope, query, limit=self.retrieval.policy.candidate_limit
            )
            for hit in self.retrieval.select_automatic(hits, existing_text):
                recalled.append(
                    MemoryItem(
                        memory_id=hit.source_id,
                        content_version=hit.source_version,
                        content=hit.text,
                        source_kind=hit.source_kind,
                        occurred_at_utc=hit.occurred_at_utc,
                        context_label=hit.context_label,
                    )
                )
        else:
            query = ""
        versions = [
            SourceVersion(
                kind="community", source_id=scope.community_id, version=str(community.state_version)
            ),
            SourceVersion(
                kind="memory_search",
                source_id=character_id,
                version=self.retrieval.source_version(
                    connection,
                    SearchScope(
                        scope.community_id,
                        character_id,
                        now,
                        scope.conversation_id,
                        scope.observation_upper_sequence,
                        conversations=boundaries,
                    ),
                ),
            ),
        ]
        versions.extend(character.source_versions)
        versions.extend(
            SourceVersion(
                kind="memory_view",
                source_id=f"{character_id}/{row['view_kind']}",
                version=row["content_version"],
            )
            for row in views
        )
        versions.extend(
            SourceVersion(
                kind=item.source_kind, source_id=item.memory_id, version=item.content_version
            )
            for item in recalled
        )
        versions.extend(
            SourceVersion(
                kind="thought", source_id=thought.thought_id, version=thought.content_version
            )
            for thought in {item.thought_id: item for item in history_thoughts}.values()
        )
        versions.append(
            SourceVersion(
                kind="conversation_membership",
                source_id=scope.conversation_id,
                version=str(membership_version),
            )
        )
        versions.extend(
            SourceVersion(kind="message", source_id=message.message_id, version="1")
            for message in inputs + tuple(history)
        )
        versions.extend(
            SourceVersion(
                kind=memory.source_kind, source_id=memory.memory_id, version=memory.content_version
            )
            for memory in resident
        )
        for digest in digests:
            versions.append(
                SourceVersion(
                    kind="conversation_digest",
                    source_id=digest["digest_id"],
                    version=digest["content_version"],
                )
            )
        versions.extend(
            SourceVersion(
                kind="segment_summary",
                source_id=summary.segment_id,
                version=summary.content_version,
            )
            for summary in summaries
        )
        snapshot = ContextSnapshot(
            snapshot_id=str(uuid4()),
            prepared_at_utc=now,
            scope=scope.model_copy(update={"conversations": boundaries}),
            self=character.self_context,
            perspective=PerspectiveContext(
                inputs=tuple(self.message(connection, message) for message in inputs),
                history=tuple(self.message(connection, message) for message in history),
                trigger_message_ids=trigger_ids,
                public_facts=tuple(
                    f"{participant.actor.kind.value}:{participant.actor.actor_id} "
                    f"{participant.display_name}"
                    for participant in observation.participants
                ),
                **({"situation": situation} if situation else {}),
            ),
            memory=MemoryContext(
                **(
                    {
                        "input_budget": input_budget,
                        "current_ratio": self.memory_policy.current_ratio,
                        "nearby_ratio": self.memory_policy.nearby_ratio,
                        "covered_message_ids": tuple(
                            sorted(
                                SegmentRepository().covered(
                                    connection,
                                    scope.community_id,
                                    character_id,
                                    {
                                        r["segment_id"]
                                        for r in eligible
                                        if r["status"] == "ingested"
                                    },
                                )
                            )
                        ),
                    }
                    if input_budget is not None
                    else {}
                ),
                retrieval_prepared=self.retrieval.vectors is None or not query.strip(),
                retrieval_query=query,
                resident=resident,
                core_memory=view_content.get("core_memory", ""),
                state_summary=view_content.get("state_summary", ""),
                recalled=tuple(recalled),
                session_digest="\n\n".join(row["content"] for row in digests),
                history_thoughts=tuple(history_thoughts),
                segment_summaries=tuple(summaries),
            ),
            environment=EnvironmentContext(
                world_time_utc=community.world_time_utc,
                community_status=community.status.value,
                conversation_kind=conversation.kind.value,
                timezone=community.timezone,
                world_description=community.world_description,
                community_rules=community.community_rules,
                community_version=community.state_version,
            ),
            action_space=ActionSpace(
                output_contracts=(CHARACTER_EXPRESSION_CONTRACT,), tools=tools
            ),
            source_versions=tuple(versions),
        )
        if not apply_budget:
            return snapshot
        selected = budget_snapshot(snapshot, self.policy.input_max_chars)
        if input_budget is not None:
            local = {
                s.segment_id
                for s in snapshot.memory.segment_summaries
                if any(c.conversation_id == scope.conversation_id for c in s.conversations)
            }
            if local - {s.segment_id for s in selected.memory.segment_summaries}:
                return snapshot.model_copy(
                    update={
                        "memory": snapshot.memory.model_copy(update={"context_prepared": False})
                    }
                )
        return selected

    def message(self, connection: sqlite3.Connection, message: Message) -> ObservedMessage:
        return ObservedMessage(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            sequence=message.sequence,
            sender=message.sender,
            sender_name=(
                self.perspective.actor_name(connection, message.community_id, message.sender)
                if isinstance(message.sender, ActorRef)
                else message.sender.source_id
            ),
            text=message.text,
            occurred_at_utc=message.created_at_utc,
            reply_to_message_id=message.reply_to_message_id,
            mentions=message.mentions,
            mention_names=tuple(
                self.perspective.actor_name(connection, message.community_id, actor)
                for actor in message.mentions
            ),
            visibility="仅指定受众可见" if message.visibility == "recipients" else "会话内可见",
        )
