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
from echo_commons.agents.contracts.output import CHARACTER_MESSAGE_CONTRACT
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
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
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
        entries: MemoryEntryRepository,
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
        self.entries, self.provenance, self.perspective, self.retrieval = (
            entries,
            provenance,
            perspective,
            retrieval,
        )

        self.character_context = CharacterContext(
            catalog, instances, states, relationships, perspective, capabilities
        )

    def prepare(
        self,
        connection: sqlite3.Connection,
        turn: SocialTurn,
        member: Membership,
        inputs: tuple[Message, ...],
        now: datetime,
    ) -> ContextSnapshot:
        character_id = member.actor.actor_id
        instance = self.character_context.instances.get(connection, turn.community_id, character_id)
        instance.require_ready()
        views = (
            MemoryViews().read(connection, turn.community_id, character_id)
            if instance.memory_mode is MemoryMode.FULL
            else ()
        )
        view_content = {row["view_kind"]: row["content"] for row in views}
        community = self.communities.get(connection, turn.community_id)
        conversation = self.conversations.get(connection, turn.community_id, turn.conversation_id)
        observation = self.perspective.observe(
            connection,
            ObservationScope(
                turn.community_id, turn.conversation_id, member.actor, turn.observation_max_sequence
            ),
        )
        input_ids = {message.message_id for message in inputs}
        continuity_upper = min(turn.observation_max_sequence, inputs[0].sequence - 1)
        digest = self.provenance.latest_digest(
            connection,
            turn.community_id,
            character_id,
            turn.conversation_id,
            through_sequence=continuity_upper,
            recorded_before=now,
        )
        summaries = []
        summary_chars = 0
        for row in self.provenance.context_summaries(
            connection,
            turn.community_id,
            character_id,
            turn.conversation_id,
            after_sequence=digest["covers_through_sequence"] if digest else 0,
            through_sequence=continuity_upper,
            recorded_before=now,
        ):
            if summary_chars + len(row["summary_text"]) > 8000:
                break
            summary_chars += len(row["summary_text"])
            summaries.append(
                ConversationSummary(
                    segment_id=row["segment_id"],
                    content_version=row["summary_version"],
                    content=row["summary_text"],
                    first_sequence=row["first_message_sequence"],
                    last_sequence=row["last_message_sequence"],
                )
            )
        summaries.reverse()
        history = []
        covered_count = 0
        remaining = self.policy.recent_message_max_chars
        for message in reversed(observation.messages):
            if message.message_id in input_ids:
                continue
            if (digest and message.sequence <= digest["covers_through_sequence"]) or any(
                summary.first_sequence <= message.sequence <= summary.last_sequence
                for summary in summaries
            ):
                if covered_count >= self.policy.covered_message_overlap:
                    break
                covered_count += 1
            if len(history) >= self.policy.recent_message_limit or len(message.text) > remaining:
                break
            history.append(message)
            remaining -= len(message.text)
        history.reverse()
        thoughts = ThoughtRepository().for_results(
            connection,
            turn.community_id,
            character_id,
            turn.conversation_id,
            tuple(
                dict.fromkeys(
                    message.result_id
                    for message in history
                    if message.sender == member.actor and message.result_id
                )
            ),
            now,
        )
        history_thoughts = []
        for message in history:
            thought = thoughts.get(message.result_id)
            if thought is None or len(thought["content"]) > remaining:
                continue
            history_thoughts.append(
                HistoricalThought(
                    message_id=message.message_id,
                    thought_id=thought["thought_id"],
                    content_version=thought["content_version"],
                    content=thought["content"],
                )
            )
            remaining -= len(thought["content"])
        targets = {participant.actor for participant in observation.participants}
        targets.update(
            message.sender
            for message in inputs + tuple(history)
            if isinstance(message.sender, ActorRef)
        )
        character = self.character_context.prepare(
            connection,
            turn.community_id,
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
            )
            for row in self.entries.active_rows(
                connection, turn.community_id, character_id, valid_at=now, recorded_before=now
            )
            if row["visibility"] == "resident"
        )[: self.policy.resident_memory_limit]
        tools = character.self_context.capabilities
        scope = SearchScope(
            turn.community_id,
            character_id,
            now,
            turn.conversation_id,
            turn.observation_max_sequence,
        )
        query = "\n".join(message.text for message in inputs)[-256:]
        if len(query) < 40 and any(
            word in query for word in ("那件", "那个", "之前", "后来", "他", "她")
        ):
            query = ("\n".join(message.text for message in history[-2:]) + "\n" + query)[-256:]
        recalled = []
        existing_text = {item.content for item in resident}
        existing_text.update(item.content for item in summaries)
        existing_text.update(message.text for message in inputs + tuple(history))
        recalled_chars = 0
        if query.strip().strip("。！!？?，, ") not in {
            "你好",
            "嗨",
            "嗯",
            "好的",
            "好",
            "谢谢",
            "哈哈",
        }:
            for hit in self.retrieval.search(
                connection, scope, query, limit=self.policy.automatic_memory_limit
            ):
                if hit.text in existing_text:
                    continue
                if recalled_chars + len(hit.text) > self.policy.automatic_memory_max_chars:
                    continue
                recalled.append(
                    MemoryItem(
                        memory_id=hit.source_id,
                        content_version=hit.source_version,
                        content=hit.text,
                        source_kind=hit.source_kind,
                        occurred_at_utc=hit.occurred_at_utc,
                    )
                )
                recalled_chars += len(hit.text)
        else:
            query = ""
        versions = [
            SourceVersion(
                kind="community", source_id=turn.community_id, version=str(community.state_version)
            ),
            SourceVersion(
                kind="memory_search",
                source_id=character_id,
                version=self.retrieval.source_version(
                    connection,
                    SearchScope(
                        turn.community_id,
                        character_id,
                        now,
                        turn.conversation_id,
                        turn.observation_max_sequence,
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
                source_id=turn.conversation_id,
                version=str(turn.membership_version),
            )
        )
        versions.extend(
            SourceVersion(kind="message", source_id=message.message_id, version="1")
            for message in inputs + tuple(history)
        )
        versions.extend(
            SourceVersion(
                kind="memory_entry", source_id=memory.memory_id, version=memory.content_version
            )
            for memory in resident
        )
        if digest:
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
            scope=SnapshotScope(
                community_id=turn.community_id,
                character_id=character_id,
                conversation_id=turn.conversation_id,
                membership_id=member.membership_id,
                observation_upper_sequence=turn.observation_max_sequence,
                social_turn_id=turn.social_turn_id,
            ),
            self=character.self_context,
            perspective=PerspectiveContext(
                inputs=tuple(self.message(connection, message) for message in inputs),
                history=tuple(self.message(connection, message) for message in history),
                public_facts=tuple(
                    f"{participant.actor.kind.value}:{participant.actor.actor_id} "
                    f"{participant.display_name}"
                    for participant in observation.participants
                ),
            ),
            memory=MemoryContext(
                retrieval_prepared=self.retrieval.vectors is None or not query.strip(),
                retrieval_query=query,
                resident=resident,
                core_memory=view_content.get("core_memory", ""),
                state_summary=view_content.get("state_summary", ""),
                recalled=tuple(recalled),
                session_digest=digest["content"] if digest else "",
                history_thoughts=tuple(history_thoughts),
                segment_summaries=tuple(summaries),
            ),
            environment=EnvironmentContext(
                world_time_utc=community.world_time_utc,
                community_status=community.status.value,
                conversation_kind=conversation.kind.value,
            ),
            action_space=ActionSpace(output_contracts=(CHARACTER_MESSAGE_CONTRACT,), tools=tools),
            source_versions=tuple(versions),
        )
        return budget_snapshot(snapshot, self.policy.input_max_chars)

    def message(self, connection: sqlite3.Connection, message: Message) -> ObservedMessage:
        return ObservedMessage(
            message_id=message.message_id,
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
        )
