import sqlite3
from datetime import datetime

from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.reflection.contexts.graph import GraphContext
from echo_commons.modules.reflection.contracts.context import (
    DigestMaterial,
    GraphContextSnapshot,
    SummaryMaterial,
)
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind


class SummaryContext:
    def __init__(self, graph: GraphContext, provenance: MemoryProvenanceRepository) -> None:
        self.graph, self.provenance = graph, provenance

    def prepare(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        graph_kind: ReflectionGraphKind,
        now: datetime,
    ) -> GraphContextSnapshot:
        if graph_kind not in {
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            ReflectionGraphKind.MEMORY_ORGANIZE,
        }:
            raise ValueError("Summary context requires a supported summary graph")
        batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
        rows = self.provenance.batch_summaries(connection, batch)
        materials = []
        if graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS and batch.previous_digest_id:
            previous = self.provenance.get_digest(
                connection,
                community_id,
                character_id,
                batch.conversation_id,
                batch.previous_digest_id,
            )
            materials.append(
                DigestMaterial(
                    source_id=previous["digest_id"],
                    version=previous["content_version"],
                    content=previous["content"],
                    covers_through_sequence=previous["covers_through_sequence"],
                )
            )
        materials.extend(
            SummaryMaterial(
                source_id=row["segment_id"],
                version=row["summary_version"],
                content=row["summary_text"],
                first_sequence=row["first_message_sequence"],
                last_sequence=row["last_message_sequence"],
            )
            for row in rows
        )
        return self.graph.prepare(
            connection,
            community_id,
            character_id,
            batch.conversation_id,
            rows[-1]["last_message_sequence"],
            graph_kind,
            "memory_summary_batch",
            batch.batch_id,
            batch.source_version,
            tuple(materials),
            now,
        )
