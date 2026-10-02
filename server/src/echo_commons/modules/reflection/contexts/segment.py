import sqlite3
from datetime import datetime

from echo_commons.agents.contracts.context import (
    ObservedMessage,
)
from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.sources import SourceKind
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval
from echo_commons.modules.perspective.contracts import ObservationScope, WorldReader
from echo_commons.modules.reflection.contexts.graph import GraphContext, ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.sources import (
    ReflectionSources,
    ReflectionSourceUnavailable,
)
from echo_commons.modules.reflection.contracts.context import (
    GraphContextSnapshot,
    MessageMaterial,
    ThoughtMaterial,
)
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.actors import ActorRef


class SegmentContext:
    def __init__(
        self,
        policy: ReflectionContextPolicy,
        characters: CharacterContext,
        communities: CommunityReader,
        conversations: ConversationReader,
        perspective: WorldReader,
        entries: MemoryEntryRepository,
        segments: SegmentRepository,
        thoughts: ThoughtRepository,
        retrieval: MemoryRetrieval,
    ) -> None:
        self.graph = GraphContext(
            policy, characters, communities, conversations, perspective, entries, retrieval
        )
        self.perspective, self.segments, self.thoughts = perspective, segments, thoughts
        self.sources = ReflectionSources(
            perspective, segments, thoughts, MemoryProvenanceRepository()
        )

    def prepare(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        segment_id: str,
        now: datetime,
    ) -> GraphContextSnapshot:
        segment = self.segments.get(connection, community_id, character_id, segment_id)
        observation = self.perspective.observe(
            connection,
            ObservationScope(
                community_id,
                segment.conversation_id,
                ActorRef("character", character_id),
                segment.last_sequence,
            ),
        )
        visible = {message.message_id: message for message in observation.messages}
        materials = []
        for source in segment.sources:
            if source.kind is SourceKind.MESSAGE:
                message = visible.get(source.source_id)
                if message is None or source.version != "1":
                    raise ReflectionSourceUnavailable(
                        "Segment message is outside its observation scope"
                    )
                materials.append(
                    MessageMaterial(
                        source_id=source.source_id,
                        version=source.version,
                        mentions=message.mentions,
                        message=ObservedMessage(
                            message_id=message.message_id,
                            sequence=message.sequence,
                            sender=message.sender,
                            sender_name=(
                                self.perspective.actor_name(
                                    connection, community_id, message.sender
                                )
                                if isinstance(message.sender, ActorRef)
                                else message.sender.source_id
                            ),
                            text=message.text,
                            occurred_at_utc=message.created_at_utc,
                            reply_to_message_id=message.reply_to_message_id,
                        ),
                    )
                )
            else:
                thought = self.thoughts.get(
                    connection, community_id, character_id, source.source_id
                )
                if (
                    thought["content"] is None
                    or thought["content_version"] != source.version
                    or thought["segment_id"] != segment_id
                    or thought["conversation_id"] != segment.conversation_id
                ):
                    raise ReflectionSourceUnavailable("Segment Thought content is unavailable")
                materials.append(
                    ThoughtMaterial(
                        source_id=source.source_id,
                        version=source.version,
                        content=thought["content"],
                        occurred_at_utc=utc_datetime(thought["created_at_utc"]),
                    )
                )
        return self.graph.prepare(
            connection,
            community_id,
            character_id,
            segment.conversation_id,
            segment.last_sequence,
            ReflectionGraphKind.SEGMENT_REFLECT,
            "memory_segment",
            segment_id,
            segment.source_version,
            tuple(materials),
            now,
        )
