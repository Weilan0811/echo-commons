from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from echo_commons.domain.memory import MemorySegmentStatus
from echo_commons.observability.trace import safe_trace_payload
from echo_commons.runtime.modules import ReflectionModule
from echo_commons.runtime.reflection.continuity_context import (
    ContinuityCompressionSnapshotPayload,
    ContinuityCompressionTrigger,
)
from echo_commons.runtime.reflection.coordinator import ReflectionGraphStart
from echo_commons.runtime.reflection.memory_context import (
    MemoryOrganizationSnapshotPayload,
    MemoryOrganizationTrigger,
)
from echo_commons.store.memory_provenance import MemoryProvenanceRepository


class ReflectionGraphScheduler:
    """Create a GraphRun from a reflection trigger."""

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime

    async def schedule_segment_reflection(
        self,
        segment_id: UUID,
        *,
        now_utc: datetime | None = None,
    ) -> ReflectionGraphStart:
        await self.runtime.ensure_started()
        now = now_utc or self.runtime.clock()
        async with self.runtime.database.transaction(immediate=True) as connection:
            segment = await self.runtime.memory_segments.get(segment_id, connection=connection)
            if segment is None:
                raise LookupError("reflection_segment_not_found")
            if segment.status not in {MemorySegmentStatus.SEALED, MemorySegmentStatus.INGESTED}:
                raise ValueError("reflection_segment_is_not_ready")
            started = await self.runtime.reflection_graph_coordinator.start_segment(
                segment.segment_id,
                now_utc=now,
                connection=connection,
            )
            await self._record_started(started, now=now, connection=connection)
        if self.runtime.reflection_wakeup is not None:
            self.runtime.reflection_wakeup.set()
        return started

    async def schedule_memory_organization(
        self,
        trigger: MemoryOrganizationTrigger,
        *,
        now_utc: datetime | None = None,
    ) -> ReflectionGraphStart | None:
        """冻结可用摘要批次，并创建一个 memory_organize GraphRun。"""

        await self.runtime.ensure_started()
        now = now_utc or self.runtime.clock()
        async with self.runtime.database.transaction(immediate=True) as connection:
            batch = await MemoryProvenanceRepository().freeze_batch(
                trigger.account_id,
                trigger.conversation_id,
                trigger.character_id,
                through_sequence=trigger.through_sequence,
                now_utc=now,
                connection=connection,
                limit=trigger.limit,
                consumer="memory_organize",
            )
            if batch is None:
                return None
            started = await self.runtime.reflection_graph_coordinator.start_memory_organization(
                MemoryOrganizationSnapshotPayload(
                    batch_id=batch.batch_id,
                    account_id=batch.account_id,
                    character_id=batch.character_id,
                ),
                now_utc=now,
                connection=connection,
            )
            await self._record_started(started, now=now, connection=connection)
        if self.runtime.reflection_wakeup is not None:
            self.runtime.reflection_wakeup.set()
        return started

    async def schedule_continuity_compression(
        self,
        trigger: ContinuityCompressionTrigger,
        *,
        now_utc: datetime | None = None,
    ) -> ReflectionGraphStart | None:
        """冻结连续性摘要批次，并创建一个 continuity_compress GraphRun。"""

        await self.runtime.ensure_started()
        now = now_utc or self.runtime.clock()
        async with self.runtime.database.transaction(immediate=True) as connection:
            batch = await MemoryProvenanceRepository().freeze_batch(
                trigger.account_id,
                trigger.conversation_id,
                trigger.character_id,
                through_sequence=trigger.through_sequence,
                now_utc=now,
                connection=connection,
                limit=trigger.limit,
                consumer="continuity_compress",
                max_material_chars=self.runtime.settings.reflection_max_material_chars,
            )
            if batch is None:
                return None
            started = await self.runtime.reflection_graph_coordinator.start_continuity_compression(
                ContinuityCompressionSnapshotPayload(
                    batch_id=batch.batch_id,
                    account_id=batch.account_id,
                    character_id=batch.character_id,
                ),
                now_utc=now,
                connection=connection,
            )
            await self._record_started(started, now=now, connection=connection)
        if self.runtime.reflection_wakeup is not None:
            self.runtime.reflection_wakeup.set()
        return started

    async def _record_started(
        self,
        started: ReflectionGraphStart,
        *,
        now: datetime,
        connection,
    ) -> None:
        run = started.graph_run
        await self.runtime.task_traces.enqueue(
            trace_id=uuid5(
                NAMESPACE_URL,
                f"reflection-graph-started:{run.graph_run_id}:{run.execution_generation}",
            ),
            correlation_id=run.trace_id or run.graph_run_id,
            kind="reflection_graph.started",
            entity_type="reflection_graph_run",
            entity_id=str(run.graph_run_id),
            payload=safe_trace_payload(
                "reflection_graph.started",
                graph_kind=str(getattr(run.graph_kind, "value", run.graph_kind)),
                graph_version=run.graph_version,
                execution_generation=run.execution_generation,
                source_count=len(run.source_scope.sources),
            ),
            created_at=now,
            connection=connection,
        )


__all__ = ["ReflectionGraphScheduler"]
