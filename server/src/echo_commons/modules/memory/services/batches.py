from datetime import UTC, datetime

from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.memory.domain.summaries import SummaryConsumer, SummaryReference
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class SummaryBatches:
    def __init__(
        self,
        database,
        instances,
        conversations,
        perspective,
        provenance,
        *,
        max_materials,
        max_chars,
    ):
        self.database, self.instances, self.conversations = database, instances, conversations
        self.perspective, self.provenance = perspective, provenance
        self.max_materials, self.max_chars = max_materials, max_chars

    def freeze(self, community_id, character_id, consumer, *, limit=16):
        with self.database.transaction() as connection:
            return self.freeze_in(connection, community_id, character_id, consumer, limit=limit)

    def freeze_in(
        self, connection, community_id, character_id, consumer, *, limit=16, observed_at=None
    ):
        now = observed_at or datetime.now(UTC)
        result = self.select(connection, community_id, character_id, consumer, limit=limit, now=now)
        if result is None:
            return None
        selected, previous, _ = result
        consumer = SummaryConsumer(consumer)
        if consumer is SummaryConsumer.CONTINUITY and not any(
            row["summary_text"] for row in selected
        ):
            self.provenance.consume_continuity(
                connection,
                tuple(
                    SummaryReference(row["segment_id"], row["summary_version"] or "")
                    for row in selected
                ),
                now,
            )
            return None
        raw = None
        if consumer is SummaryConsumer.ORGANIZATION:
            selected, raw = self.original_selection(
                connection, community_id, character_id, selected, now
            )
        return self.provenance.create_batch(
            connection,
            community_id,
            character_id,
            selected,
            previous,
            now,
            consumer=consumer,
            organization_sources=raw,
        )

    def originals(self, connection, community, character, now):
        actor = ActorRef("character", character)
        boundaries = self.perspective.freeze(connection, community, actor, now)
        messages = self.perspective.experiences(connection, community, actor, boundaries, now)
        return boundaries, {m.message_id: m for m in messages}

    def original_selection(self, connection, community, character, summaries, now):
        _, visible = self.originals(connection, community, character, now)
        consumed = {
            tuple(row)
            for row in connection.execute(
                "SELECT source_kind,source_id,source_version FROM memory_organization_coverage "
                "WHERE character_id=? AND stage='cognitions'",
                (character,),
            )
        }
        chosen, references, count, chars = [], [], 0, 0
        for summary in summaries:
            segment = SegmentRepository().get(
                connection, community, character, summary["segment_id"]
            )
            originals = {source.source_id: source for source in segment.sources}
            thoughts = {}
            messages = []
            for source in segment.sources:
                if source.kind == "thought":
                    row = ThoughtRepository().get(
                        connection, community, character, source.source_id
                    )
                    if row["content"] is None or row["content_version"] != source.version:
                        raise ConflictError("Long-term Thought source is unavailable")
                    thoughts[row["result_id"]] = (source, len(row["content"]))
                else:
                    message = visible.get(source.source_id)
                    if message is None:
                        raise ConflictError("Long-term message is outside observation")
                    messages.append(message)
            added = False
            for message in sorted(messages, key=lambda m: (m.created_at_utc, m.message_id)):
                group = [(originals[message.message_id], len(message.text))]
                if message.result_id in thoughts:
                    group.append(thoughts[message.result_id])
                group = [
                    (source, size)
                    for source, size in group
                    if (source.kind.value, source.source_id, source.version) not in consumed
                ]
                if not group:
                    continue
                extra_count = len(group) + int(not added and bool(summary["summary_text"]))
                extra_chars = sum(size for _, size in group) + (
                    len(summary["summary_text"] or "") if not added else 0
                )
                if count + extra_count > self.max_materials or chars + extra_chars > self.max_chars:
                    if not references:
                        raise ConflictError(
                            "One original message group exceeds reflection input budget"
                        )
                    return tuple(chosen), tuple(references)
                if not added:
                    chosen.append(summary)
                    added = True
                references.extend(
                    (source.kind.value, source.source_id, source.version) for source, _ in group
                )
                count += extra_count
                chars += extra_chars
        if not references:
            raise ConflictError("Long-term source selection has no unprocessed original material")
        return tuple(chosen), tuple(references)

    def select(self, connection, community_id, character_id, consumer, *, limit=16, now=None):
        consumer = SummaryConsumer(consumer)
        now = now or datetime.now(UTC)
        if limit < 1:
            raise ValueError("Summary batch size must be positive")
        instance = self.instances.get(connection, community_id, character_id)
        instance.require_ready()
        if instance.memory_mode is MemoryMode.SIMPLE and consumer is SummaryConsumer.ORGANIZATION:
            raise ConflictError("Simple mode does not organize long-term memory")
        _, visible = self.originals(connection, community_id, character_id, now)
        candidates = self.provenance.eligible_segments(
            connection, community_id, character_id, frozenset(visible), now
        )
        previous = (
            self.provenance.latest_digests(
                connection,
                community_id,
                character_id,
                recorded_before=now,
                eligible_segment_ids=frozenset(row["segment_id"] for row in candidates),
            )
            if consumer is SummaryConsumer.CONTINUITY
            else ()
        )
        count, chars = len(previous), sum(len(row["content"]) for row in previous)
        selected, full = [], False
        for segment in candidates:
            if segment["status"] != "ingested":
                break
            if consumer is SummaryConsumer.CONTINUITY:
                if self.provenance.continuity_consumed(connection, segment["segment_id"]):
                    continue
            elif self.provenance.organization_consumed(
                connection, segment["segment_id"], segment["summary_version"] or ""
            ):
                continue
            added_count = int(bool(segment["summary_text"]))
            added_chars = len(segment["summary_text"] or "")
            if count + added_count > self.max_materials or chars + added_chars > self.max_chars:
                if not selected:
                    raise ConflictError("Summary source exceeds configured material budget")
                full = True
                break
            selected.append(segment)
            chars += added_chars
            count += added_count
            if len(selected) >= limit:
                full = True
                break
        return (tuple(selected), previous, full) if selected else None
