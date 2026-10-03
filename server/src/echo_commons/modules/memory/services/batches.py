from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.summaries import SummaryBatch, SummaryConsumer
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.perspective.contracts import ObservationScope, WorldReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class SummaryBatches:
    def __init__(
        self,
        database: Database,
        instances: InstanceReader,
        conversations: ConversationReader,
        perspective: WorldReader,
        provenance: MemoryProvenanceRepository,
        *,
        max_materials: int,
        max_chars: int,
    ) -> None:
        self.database, self.instances, self.conversations = database, instances, conversations
        self.perspective, self.provenance = perspective, provenance
        self.max_materials, self.max_chars = max_materials, max_chars

    def freeze(
        self,
        community_id: str,
        character_id: str,
        conversation_id: str,
        consumer: SummaryConsumer,
        *,
        through_sequence: int,
        limit: int = 16,
    ) -> SummaryBatch | None:
        consumer = SummaryConsumer(consumer)
        if limit < 1:
            raise ValueError("Summary batch size must be positive")
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            self.instances.get(connection, community_id, character_id)
            conversation = self.conversations.get(connection, community_id, conversation_id)
            if not 0 <= through_sequence < conversation.next_sequence:
                raise ValueError("Summary boundary exceeds the conversation messages")
            observation = self.perspective.observe(
                connection,
                ObservationScope(
                    community_id,
                    conversation_id,
                    ActorRef("character", character_id),
                    through_sequence,
                ),
            )
            previous = (
                self.provenance.latest_digest(
                    connection,
                    community_id,
                    character_id,
                    conversation_id,
                    through_sequence=through_sequence,
                    recorded_before=now,
                )
                if consumer is SummaryConsumer.CONTINUITY
                else None
            )
            after = previous["covers_through_sequence"] if previous else 0
            count, chars = (1, len(previous["content"])) if previous else (0, 0)
            selected = []
            cursor = after
            for segment in self.provenance.candidates(
                connection, community_id, character_id, conversation_id, after, through_sequence
            ):
                if any(
                    cursor < message.sequence < segment["first_message_sequence"]
                    for message in observation.messages
                ):
                    break
                if segment["status"] != "ingested":
                    break
                if not segment["summary_text"] or (
                    consumer is SummaryConsumer.ORGANIZATION
                    and self.provenance.organization_consumed(
                        connection, segment["segment_id"], segment["summary_version"]
                    )
                ):
                    cursor = segment["last_message_sequence"]
                    continue
                if (
                    count + 1 > self.max_materials
                    or chars + len(segment["summary_text"]) > self.max_chars
                ):
                    if not selected:
                        raise ConflictError("Summary source exceeds the configured material budget")
                    break
                selected.append(segment)
                chars += len(segment["summary_text"])
                count += 1
                cursor = segment["last_message_sequence"]
                if len(selected) >= limit:
                    break
            if not selected:
                return None
            return self.provenance.create_batch(
                connection,
                community_id,
                character_id,
                conversation_id,
                tuple(selected),
                previous,
                now,
            )
