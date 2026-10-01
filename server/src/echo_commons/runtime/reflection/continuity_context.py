from __future__ import annotations

from dataclasses import dataclass

from echo_server.agents.contracts.reflection_context import (
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_server.domain.reflection_graph import GraphSourceRef, ReflectionSourceScope
from echo_server.runtime.reflection.context import (
    GraphSnapshotAssembler,
    GraphSnapshotBuild,
    SnapshotBuildContext,
    SnapshotSourceBuild,
    bound_materials,
)
from echo_server.store.memory_provenance import MemoryProvenanceRepository


@dataclass(frozen=True, slots=True)
class ContinuityCompressionSnapshotPayload:
    batch_id: str
    account_id: str
    character_id: str


@dataclass(frozen=True, slots=True)
class ContinuityCompressionTrigger:
    account_id: str
    conversation_id: str
    character_id: str
    through_sequence: int
    limit: int


class ContinuityCompressionGraphSnapshotBuilder:
    """准备上一条连续性摘要和当前冻结段摘要。"""

    def __init__(
        self,
        *,
        assembler: GraphSnapshotAssembler,
    ) -> None:
        self.assembler = assembler
        self.provenance = MemoryProvenanceRepository()

    async def build(
        self,
        payload: ContinuityCompressionSnapshotPayload,
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
            raise LookupError("continuity_compression_batch_not_found")
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

        if batch.previous_digest_id is not None:
            previous = await self.provenance.get_digest(
                batch.previous_digest_id,
                account_id=batch.account_id,
                conversation_id=batch.conversation_id,
                character_id=batch.character_id,
                connection=context.connection,
            )
            if previous is None:
                raise LookupError("continuity_compression_previous_digest_not_found")
            digest_ref = f"digest:{previous['digest_id']}"
            required_source_refs.add(digest_ref)
            materials.append(
                ReflectionSourceMaterial(
                    source_ref=digest_ref,
                    source_kind="conversation_digest",
                    content=previous["content"],
                    content_version=previous["content_version"],
                )
            )
            source_scope.append(
                GraphSourceRef(
                    kind="conversation_digest",
                    ref=digest_ref,
                    version=previous["content_version"],
                )
            )

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

        first_sequence = min(item["first_message_sequence"] for item in items)
        last_sequence = max(item["last_message_sequence"] for item in items)

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


__all__ = [
    "ContinuityCompressionGraphSnapshotBuilder",
    "ContinuityCompressionSnapshotPayload",
    "ContinuityCompressionTrigger",
]
