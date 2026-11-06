from datetime import UTC, datetime

from echo_commons.agents.contracts.context import ConversationSummary
from echo_commons.agents.contracts.input import SourceVersion
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.context import HistorySummaryRequired
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.actors import ActorRef


class ContextPreparation:
    def __init__(self, context, sealing, workflow, budget):
        self.context, self.sealing, self.workflow = context, sealing, workflow
        self.budget = budget

    def refresh(self, connection, snapshot):
        scope = snapshot.scope
        now = datetime.now(UTC)
        visible = self.context.perspective.experiences(
            connection,
            scope.community_id,
            ActorRef("character", scope.character_id),
            scope.conversations,
            snapshot.prepared_at_utc,
        )
        # 摘要可以覆盖同一读取范围内的当前输入；当前原文仍由输入区完整保留。
        ids = frozenset(m.message_id for m in visible)
        eligible = self.context.provenance.eligible_segments(
            connection,
            scope.community_id,
            scope.character_id,
            ids,
            now,
            observed_before=snapshot.prepared_at_utc,
        )
        completed = [r for r in eligible if r["status"] == "ingested"]
        digests = self.context.provenance.latest_digests(
            connection,
            scope.community_id,
            scope.character_id,
            recorded_before=now,
            eligible_segment_ids=frozenset(r["segment_id"] for r in eligible),
        )
        digest_segments = set().union(
            *(self.context.provenance.digest_segments(connection, d["digest_id"]) for d in digests)
        )
        covered = SegmentRepository().covered(
            connection, scope.community_id, scope.character_id, {r["segment_id"] for r in completed}
        )
        overlap = {}
        history = []
        for message in reversed(snapshot.perspective.history):
            if message.message_id in covered:
                count = overlap.get(message.conversation_id, 0)
                if count >= self.context.policy.covered_message_overlap:
                    continue
                overlap[message.conversation_id] = count + 1
            history.append(message)
        history.reverse()
        retained_ids = {m.message_id for m in history}
        summaries = []
        versions = list(snapshot.source_versions)
        for row in completed:
            if not row["summary_text"] or row["segment_id"] in digest_segments:
                continue
            segment = SegmentRepository().get(
                connection, scope.community_id, scope.character_id, row["segment_id"]
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
            version = SourceVersion(
                kind="segment_summary",
                source_id=segment.segment_id,
                version=segment.summary_version,
            )
            if version not in versions:
                versions.append(version)
        for digest in digests:
            version = SourceVersion(
                kind="conversation_digest",
                source_id=digest["digest_id"],
                version=digest["content_version"],
            )
            if version not in versions:
                versions.append(version)
        return snapshot.model_copy(
            update={
                "source_versions": tuple(versions),
                "perspective": snapshot.perspective.model_copy(update={"history": tuple(history)}),
                "memory": snapshot.memory.model_copy(
                    update={
                        "history_thoughts": tuple(
                            t
                            for t in snapshot.memory.history_thoughts
                            if t.message_id in retained_ids
                        ),
                        "covered_message_ids": tuple(sorted(covered)),
                        "segment_summaries": tuple(summaries),
                        "session_digest": "\n\n".join(d["content"] for d in digests),
                    }
                ),
            }
        )

    def prepare(self, connection, snapshot, *, measure=None):
        snapshot = self.refresh(connection, snapshot)
        try:
            selected = self.budget(
                snapshot, snapshot.memory.input_budget.max_chars, measure=measure
            )
            local = {
                s.segment_id
                for s in snapshot.memory.segment_summaries
                if any(c.conversation_id == snapshot.scope.conversation_id for c in s.conversations)
            }
            if local - {s.segment_id for s in selected.memory.segment_summaries}:
                self._compress(connection, snapshot.scope)
            return selected
        except HistorySummaryRequired as required:
            scope = snapshot.scope
            # 同一角色的整理仍按原消费者串行，等待不持有模型调用或业务租约。
            if self.workflow.blocked(
                connection,
                scope.community_id,
                scope.character_id,
                ReflectionGraphKind.SEGMENT_REFLECT,
            ):
                return None
            assigned = connection.execute(
                "SELECT DISTINCT s.segment_id FROM memory_segment_sources s "
                "JOIN memory_segments m USING(segment_id) WHERE m.community_id=? "
                "AND m.character_id=? AND m.status='sealed' AND s.source_kind='message' "
                "ORDER BY m.position",
                (scope.community_id, scope.character_id),
            ).fetchall()
            needed = set(required.message_ids)
            for row in assigned:
                sources = SegmentRepository().references(connection, row["segment_id"])
                if any(s.source_id in needed for s in sources):
                    self.workflow.coordinator.start_segment_in(
                        connection,
                        scope.community_id,
                        scope.character_id,
                        row["segment_id"],
                    )
                    return None
            segment = self.sealing.freeze(
                connection,
                scope.community_id,
                scope.character_id,
                observed_at=snapshot.prepared_at_utc,
                message_ids=needed,
                boundaries=scope.conversations,
            )
            if segment is not None:
                self.workflow.coordinator.start_segment_in(
                    connection,
                    scope.community_id,
                    scope.character_id,
                    segment.segment_id,
                )
            return None

    def _compress(self, connection, scope):
        kind = ReflectionGraphKind.CONTINUITY_COMPRESS
        if self.workflow.blocked(connection, scope.community_id, scope.character_id, kind):
            return
        batch = self.workflow.batches.freeze_in(
            connection,
            scope.community_id,
            scope.character_id,
            SummaryConsumer.CONTINUITY,
        )
        if batch is not None:
            self.workflow.coordinator.start_summary_in(
                connection,
                scope.community_id,
                scope.character_id,
                batch.batch_id,
                kind,
            )
