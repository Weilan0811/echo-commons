from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from echo_commons.agents.contracts.reflection_context import (
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_commons.domain.memory import MemorySegment, MemorySegmentStatus
from echo_commons.domain.reflection_graph import GraphSourceRef, ReflectionSourceScope
from echo_commons.runtime.reflection.context import (
    GraphSnapshotAssembler,
    GraphSnapshotBuild,
    SnapshotBuildContext,
    SnapshotSourceBuild,
    bound_materials,
)

if TYPE_CHECKING:
    from echo_commons.runtime.modules import ReflectionModule


@dataclass(frozen=True, slots=True)
class SegmentSnapshotPayload:
    segment_id: UUID


class SegmentGraphSnapshotBuilder:
    """准备单个 MemorySegment 的反思来源。"""

    def __init__(
        self,
        runtime: ReflectionModule,
        *,
        assembler: GraphSnapshotAssembler,
    ) -> None:
        self.runtime = runtime
        self.assembler = assembler

    async def build(
        self,
        payload: SegmentSnapshotPayload,
        *,
        context: SnapshotBuildContext,
    ) -> GraphSnapshotBuild:
        segment = await self.runtime.memory_segments.get(
            payload.segment_id,
            connection=context.connection,
        )
        if segment is None:
            raise LookupError("reflection_segment_not_found")
        if segment.status not in {MemorySegmentStatus.SEALED, MemorySegmentStatus.INGESTED}:
            raise ValueError("reflection_segment_is_not_ready")
        materials, window_source_refs = await self._materials(segment, context=context)
        materials = bound_materials(
            materials,
            max_materials=self.assembler.max_materials,
            max_material_chars=self.assembler.max_material_chars,
            required_source_refs=frozenset(window_source_refs),
        )
        source_scope = ReflectionSourceScope(
            sources=(
                GraphSourceRef(
                    kind="memory_segment",
                    ref=str(segment.segment_id),
                    version=segment.source_version,
                ),
                *tuple(
                    GraphSourceRef(
                        kind=material.source_kind,
                        ref=material.source_ref,
                        version=material.content_version,
                    )
                    for material in materials
                    if material.source_ref in window_source_refs
                ),
            )
        )
        return await self.assembler.assemble(
            SnapshotSourceBuild(
                account_id=segment.account_id,
                character_id=segment.character_id,
                source_scope=source_scope,
                materials=materials,
                window=ReflectionWindowContext(
                    first_message_sequence=segment.first_message_sequence,
                    last_message_sequence=segment.last_message_sequence,
                ),
            ),
            context=context,
        )

    async def _materials(
        self,
        segment: MemorySegment,
        *,
        context: SnapshotBuildContext,
    ) -> tuple[tuple[ReflectionSourceMaterial, ...], frozenset[str]]:
        message_limit = self.runtime.settings.reflection_max_messages_per_segment
        messages = await self.runtime.runtime_messages.list_conversation_range(
            segment.account_id,
            segment.conversation_id,
            segment.first_message_sequence,
            segment.last_message_sequence,
            limit=message_limit + 1,
            connection=context.connection,
        )
        if len(messages) > message_limit:
            raise LookupError("reflection_segment_exceeds_material_budget")
        materials = [
            ReflectionSourceMaterial(
                source_ref=f"message:{message.message_id}",
                source_kind=f"conversation_{message.sender.type.value}",
                content=message.text,
                content_version=str(message.message_id),
                occurred_at_utc=message.server_timestamp_utc,
            )
            for message in messages
        ]
        thoughts = await self.runtime.thoughts.list_for_segment(
            segment.segment_id,
            connection=context.connection,
        )
        materials.extend(
            ReflectionSourceMaterial(
                source_ref=f"thought:{thought.thought_id}",
                source_kind="conversation_thought",
                content=thought.content,
                content_version=thought.content_version,
                occurred_at_utc=thought.created_at_utc,
            )
            for thought in thoughts
        )
        window_source_refs = frozenset(material.source_ref for material in materials)
        return tuple(materials), window_source_refs


__all__ = ["SegmentGraphSnapshotBuilder", "SegmentSnapshotPayload"]
