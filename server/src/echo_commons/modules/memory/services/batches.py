import sqlite3
from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.summaries import SummaryBatch, SummaryConsumer
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
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
        with self.database.transaction() as connection:
            return self.freeze_in(
                connection,
                community_id,
                character_id,
                conversation_id,
                consumer,
                through_sequence=through_sequence,
                limit=limit,
            )

    def freeze_in(
        self,
        connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        consumer: SummaryConsumer,
        *,
        through_sequence: int,
        limit: int = 16,
    ) -> SummaryBatch | None:
        result = self.select(
            connection,
            community_id,
            character_id,
            conversation_id,
            consumer,
            through_sequence=through_sequence,
            limit=limit,
        )
        if result is None:
            return None
        selected, previous, _ = result
        raw = None
        if consumer is SummaryConsumer.ORGANIZATION:
            selected, raw = self.original_selection(
                connection, community_id, character_id, conversation_id, through_sequence, selected
            )
        return self.provenance.create_batch(
            connection,
            community_id,
            character_id,
            conversation_id,
            selected,
            previous,
            datetime.now(UTC),
            organization_sources=raw,
        )

    def original_selection(self, connection, community, character, conversation, upper, summaries):
        observation = self.perspective.observe(
            connection,
            ObservationScope(community, conversation, ActorRef("character", character), upper),
        )
        visible = {message.message_id: message for message in observation.messages}
        consumed = {
            (row["source_kind"], row["source_id"], row["source_version"])
            for row in connection.execute(
                "SELECT * FROM memory_organization_coverage WHERE character_id=? "
                "AND stage='cognitions'",
                (character,),
            )
        }
        chosen, references, count, chars = [], [], 0, 0
        for summary in summaries:
            segment = SegmentRepository().get(
                connection, community, character, summary["segment_id"]
            )
            thought_by_result = {}
            messages = []
            for source in segment.sources:
                if source.kind == "thought":
                    row = ThoughtRepository().get(
                        connection, community, character, source.source_id
                    )
                    if row["content"] is None or row["content_version"] != source.version:
                        raise ConflictError("Long-term Thought source is unavailable")
                    thought_by_result[row["result_id"]] = (source, len(row["content"]))
                else:
                    message = visible.get(source.source_id)
                    if message is None:
                        raise ConflictError("Long-term message source is outside observation")
                    messages.append((source, message))
            added_summary = False
            for source, message in messages:
                group = [(source, len(message.text))]
                if message.result_id in thought_by_result:
                    group.append(thought_by_result[message.result_id])
                group = [
                    (item, size)
                    for item, size in group
                    if (item.kind.value, item.source_id, item.version) not in consumed
                ]
                if not group:
                    continue
                extra_count = len(group) + (0 if added_summary else 1)
                extra_chars = sum(size for _, size in group) + (
                    0 if added_summary else len(summary["summary_text"])
                )
                if count + extra_count > self.max_materials or chars + extra_chars > self.max_chars:
                    if not references:
                        raise ConflictError(
                            "One original message group exceeds reflection input budget"
                        )
                    return tuple(chosen), tuple(references)
                if not added_summary:
                    chosen.append(summary)
                    added_summary = True
                references.extend(
                    (item.kind.value, item.source_id, item.version) for item, _ in group
                )
                count += extra_count
                chars += extra_chars
        if not references:
            raise ConflictError(
                "Long-term source selection contains no unprocessed original material"
            )
        return tuple(chosen), tuple(references)

    def select(
        self,
        connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        consumer: SummaryConsumer,
        *,
        through_sequence: int,
        limit: int = 16,
    ) -> tuple[tuple[sqlite3.Row, ...], sqlite3.Row | None, bool] | None:
        consumer = SummaryConsumer(consumer)
        if limit < 1:
            raise ValueError("Summary batch size must be positive")
        now = datetime.now(UTC)
        instance = self.instances.get(connection, community_id, character_id)
        instance.require_ready()
        if instance.memory_mode is MemoryMode.SIMPLE and consumer is SummaryConsumer.ORGANIZATION:
            raise ConflictError("Simple mode does not organize long-term memory")
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
        budget_full = False
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
                budget_full = True
                break
            selected.append(segment)
            chars += len(segment["summary_text"])
            count += 1
            cursor = segment["last_message_sequence"]
            if len(selected) >= limit:
                budget_full = True
                break
        if not selected:
            return None
        return tuple(selected), previous, budget_full
