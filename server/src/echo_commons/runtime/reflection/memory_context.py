from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from echo_commons.agents.contracts.reflection_context import (
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_commons.domain.reflection_graph import GraphSourceRef, ReflectionSourceScope
from echo_commons.runtime.reflection.context import (
    GraphSnapshotAssembler,
    GraphSnapshotBuild,
    SnapshotBuildContext,
    SnapshotSourceBuild,
    bound_materials,
)
from echo_commons.store.memory_provenance import MemoryProvenanceRepository

if TYPE_CHECKING:
    from echo_commons.runtime.modules import ReflectionModule


@dataclass(frozen=True, slots=True)
class MemoryOrganizationSnapshotPayload:
    batch_id: str
    account_id: str
    character_id: str


@dataclass(frozen=True, slots=True)
class MemoryOrganizationTrigger:
    account_id: str
    conversation_id: str
    character_id: str
    through_sequence: int
    limit: int = 16


class MemoryOrganizationGraphSnapshotBuilder:
    """准备一个 SummaryBatch 及其原始消息材料。"""

    def __init__(
        self,
        runtime: ReflectionModule,
        *,
        assembler: GraphSnapshotAssembler,
    ) -> None:
        self.runtime = runtime
        self.assembler = assembler
        self.provenance = MemoryProvenanceRepository()

    async def build(
        self,
        payload: MemoryOrganizationSnapshotPayload,
        *,
        context: SnapshotBuildContext,
    ) -> GraphSnapshotBuild:
        batch = await self.provenance.get_batch(
            payload.batch_id,
            account_id=payload.account_id,
            character_id=payload.character_id,
            connection=context.connection,
        )
        if batch is None:
            raise LookupError("memory_organization_batch_not_found")
        items = await self.provenance.validate_batch(batch, connection=context.connection)
        materials: list[ReflectionSourceMaterial] = []
        required_source_refs: set[str] = set()
        source_scope = [
            GraphSourceRef(
                kind="memory_summary_batch",
                ref=batch.batch_id,
                version=batch.source_version,
            )
        ]
        first_sequence: int | None = None
        last_sequence: int | None = None
        for item in items:
            segment_id = item["segment_id"]
            summary_ref = f"summary:{segment_id}"
            required_source_refs.add(summary_ref)
            materials.append(
                ReflectionSourceMaterial(
                    source_ref=summary_ref,
                    source_kind="memory_segment_summary",
                    content=item["summary_text"],
                    content_version=item["summary_version"],
                )
            )
            source_scope.append(
                GraphSourceRef(
                    kind="segment_summary",
                    ref=segment_id,
                    version=item["summary_version"],
                )
            )
            source_scope.append(
                GraphSourceRef(
                    kind="memory_segment_summary",
                    ref=summary_ref,
                    version=item["summary_version"],
                )
            )
            first_sequence = _minimum(first_sequence, item["first_message_sequence"])
            last_sequence = _maximum(last_sequence, item["last_message_sequence"])
            message_limit = self.runtime.settings.reflection_max_messages_per_segment
            messages = await self.runtime.runtime_messages.list_conversation_range(
                batch.account_id,
                batch.conversation_id,
                item["first_message_sequence"],
                item["last_message_sequence"],
                limit=message_limit + 1,
                connection=context.connection,
            )
            for message in messages[:message_limit]:
                message_ref = f"message:{message.message_id}"
                source_scope.append(
                    GraphSourceRef(
                        kind=f"conversation_{message.sender.type.value}",
                        ref=message_ref,
                        version=str(message.message_id),
                    )
                )
                materials.append(
                    ReflectionSourceMaterial(
                        source_ref=message_ref,
                        source_kind=f"conversation_{message.sender.type.value}",
                        content=message.text,
                        content_version=str(message.message_id),
                        occurred_at_utc=message.server_timestamp_utc,
                    )
                )
        bounded = bound_materials(
            materials,
            max_materials=self.assembler.max_materials,
            max_material_chars=self.assembler.max_material_chars,
            required_source_refs=frozenset(required_source_refs),
        )
        selected_material_refs = {material.source_ref for material in bounded}
        source_scope = [
            source
            for source in source_scope
            if source.kind in {"memory_summary_batch", "segment_summary"}
            or source.ref in selected_material_refs
        ]
        return await self.assembler.assemble(
            SnapshotSourceBuild(
                account_id=batch.account_id,
                character_id=batch.character_id,
                source_scope=ReflectionSourceScope(sources=tuple(source_scope)),
                materials=bounded,
                window=ReflectionWindowContext(
                    first_message_sequence=first_sequence,
                    last_message_sequence=last_sequence,
                ),
            ),
            context=context,
        )


def _minimum(current: int | None, value: int) -> int:
    return value if current is None else min(current, value)


def _maximum(current: int | None, value: int) -> int:
    return value if current is None else max(current, value)


__all__ = [
    "MemoryOrganizationGraphSnapshotBuilder",
    "MemoryOrganizationSnapshotPayload",
    "MemoryOrganizationTrigger",
]
