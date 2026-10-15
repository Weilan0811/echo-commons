from echo_commons.agents.contracts.context import (
    ObservedMessage,
)
from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.sources import SourceKind
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval
from echo_commons.modules.perspective.contracts import WorldReader
from echo_commons.modules.reflection.contexts.graph import GraphContext, ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.sources import (
    ReflectionSources,
    ReflectionSourceUnavailable,
)
from echo_commons.modules.reflection.contracts.context import (
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
        records: LongTermMemoryRepository,
        segments: SegmentRepository,
        thoughts: ThoughtRepository,
        retrieval: MemoryRetrieval,
    ) -> None:
        self.graph = GraphContext(
            policy, characters, communities, conversations, perspective, records, retrieval
        )
        self.perspective, self.segments, self.thoughts = perspective, segments, thoughts
        self.sources = ReflectionSources(
            perspective, segments, thoughts, MemoryProvenanceRepository()
        )

    def materials(
        self, connection, community_id, character_id, segment_id, *, include_context=False
    ):
        segment = self.segments.get(connection, community_id, character_id, segment_id)
        messages = self.perspective.experiences(
            connection,
            community_id,
            ActorRef("character", character_id),
            segment.conversations,
            segment.sealed_at_utc,
        )
        visible = {message.message_id: message for message in messages}
        by_result = {message.result_id: message for message in messages if message.result_id}
        materials = []
        references = tuple((source, False) for source in segment.sources)
        if include_context:
            references += tuple((source, True) for source in segment.context_sources)
        for source, context in references:
            if source.kind is SourceKind.MESSAGE:
                message = visible.get(source.source_id)
                if message is None or source.version != "1":
                    raise ReflectionSourceUnavailable("Segment message is outside observation")
                materials.append(
                    MessageMaterial(
                        source_id=source.source_id,
                        version=source.version,
                        mentions=message.mentions,
                        context_only=context,
                        message=ObservedMessage(
                            message_id=message.message_id,
                            conversation_id=message.conversation_id,
                            sequence=message.sequence,
                            sender=message.sender,
                            sender_name=self.perspective.actor_name(
                                connection, community_id, message.sender
                            )
                            if isinstance(message.sender, ActorRef)
                            else message.sender.source_id,
                            text=message.text,
                            occurred_at_utc=message.created_at_utc,
                            reply_to_message_id=message.reply_to_message_id,
                            mentions=message.mentions,
                            visibility="私人交流"
                            if message.visibility == "recipients"
                            else next(
                                scene.kind
                                for scene in segment.conversations
                                if scene.conversation_id == message.conversation_id
                            ),
                        ),
                    )
                )
            else:
                thought = self.thoughts.get(
                    connection, community_id, character_id, source.source_id
                )
                message = by_result.get(thought["result_id"])
                if (
                    thought["content"] is None
                    or thought["content_version"] != source.version
                    or message is None
                    or (not context and thought["segment_id"] != segment_id)
                ):
                    raise ReflectionSourceUnavailable("Segment Thought content is unavailable")
                materials.append(
                    ThoughtMaterial(
                        source_id=source.source_id,
                        version=source.version,
                        content=thought["content"],
                        occurred_at_utc=utc_datetime(thought["created_at_utc"]),
                        conversation_id=thought["conversation_id"],
                        context_only=context,
                    )
                )
        return tuple(materials)

    def prepare(self, connection, community_id, character_id, segment_id, now):
        segment = self.segments.get(connection, community_id, character_id, segment_id)
        return self.graph.prepare(
            connection,
            community_id,
            character_id,
            ReflectionGraphKind.SEGMENT_REFLECT,
            "memory_segment",
            segment_id,
            segment.source_version,
            self.materials(
                connection, community_id, character_id, segment_id, include_context=True
            ),
            now,
            conversations=segment.conversations,
        )
