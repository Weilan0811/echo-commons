from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.memory import MemorySegment
from echo_commons.modules.memory.domain.sources import MemorySource, SourceKind
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class MemorySealing:
    def __init__(
        self,
        database: Database,
        instances: InstanceReader,
        conversations: ConversationReader,
        perspective: PerspectiveReader,
        segments: SegmentRepository,
        thoughts: ThoughtRepository,
        *,
        max_messages: int = 100,
        max_materials: int = 256,
        max_material_chars: int = 20000,
    ) -> None:
        self.database, self.instances, self.conversations = database, instances, conversations
        self.perspective, self.segments, self.thoughts = perspective, segments, thoughts
        self.max_messages, self.max_materials, self.max_material_chars = (
            max_messages,
            max_materials,
            max_material_chars,
        )

    def seal(
        self,
        community_id: str,
        character_id: str,
        conversation_id: str,
        *,
        upper_sequence: int | None = None,
        first_sequence: int | None = None,
    ) -> MemorySegment | None:
        with self.database.transaction() as connection:
            return self.freeze(
                connection,
                community_id,
                character_id,
                conversation_id,
                upper_sequence=upper_sequence,
                first_sequence=first_sequence,
            )

    def freeze(
        self,
        connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        *,
        upper_sequence: int | None = None,
        first_sequence: int | None = None,
    ) -> MemorySegment | None:
        now = datetime.now(UTC)
        self.instances.get(connection, community_id, character_id)
        conversation = self.conversations.get(connection, community_id, conversation_id)
        upper = conversation.next_sequence - 1 if upper_sequence is None else upper_sequence
        if not 0 <= upper < conversation.next_sequence:
            raise ValueError("Memory boundary exceeds the conversation messages")
        if first_sequence is not None:
            if not 1 <= first_sequence <= upper:
                raise ValueError("Memory start must be within the requested boundary")
            existing = connection.execute(
                "SELECT segment_id FROM memory_segments WHERE community_id = ? "
                "AND character_id = ? AND conversation_id = ? AND first_message_sequence = ?",
                (community_id, character_id, conversation_id, first_sequence),
            ).fetchone()
            if existing is not None:
                segment = self.segments.get(connection, community_id, character_id, existing[0])
                if segment.last_sequence > upper:
                    raise ConflictError("Existing segment exceeds the requested boundary")
                return segment
        messages, thoughts = self.pending(
            connection, community_id, character_id, conversation_id, upper
        )
        if not messages:
            return None
        if first_sequence is not None and messages[0].sequence != first_sequence:
            raise ConflictError("Requested start differs from the next visible unsealed message")
        sources = []
        selected = []
        chars = 0
        for message in messages:
            thought = thoughts.get(message.result_id)
            added = 2 if thought is not None else 1
            material_chars = len(message.text) + (len(thought["content"]) if thought else 0)
            if (
                len(selected) >= self.max_messages
                or len(sources) + added > self.max_materials
                or chars + material_chars > self.max_material_chars
            ):
                if not selected:
                    raise ConflictError("One memory event exceeds the configured material budget")
                break
            selected.append(message)
            chars += material_chars
            sources.append(MemorySource(SourceKind.MESSAGE, message.message_id, "1"))
            if thought is not None:
                sources.append(
                    MemorySource(
                        SourceKind.THOUGHT,
                        thought["thought_id"],
                        thought["content_version"],
                    )
                )
        return self.segments.add(
            connection,
            community_id,
            character_id,
            conversation_id,
            selected[0].sequence,
            selected[-1].sequence,
            tuple(sources),
            now,
        )

    def pending(self, connection, community_id, character_id, conversation_id, upper):
        scope = ObservationScope(
            community_id, conversation_id, ActorRef("character", character_id), upper
        )
        visible = self.perspective.messages(connection, scope)
        covered = self.segments.covered_messages(
            connection, community_id, character_id, conversation_id
        )
        messages = tuple(message for message in visible if message.message_id not in covered)
        if not messages:
            return (), {}
        stop = self.segments.next_start(
            connection, community_id, character_id, conversation_id, messages[0].sequence
        )
        if stop is not None:
            messages = tuple(message for message in messages if message.sequence < stop)
        results = {message.result_id for message in messages if message.result_id is not None}
        thoughts = {
            row["result_id"]: row
            for row in self.thoughts.unsegmented(
                connection, community_id, character_id, conversation_id, messages[-1].sequence
            )
            if row["result_id"] in results
        }
        return messages, thoughts
