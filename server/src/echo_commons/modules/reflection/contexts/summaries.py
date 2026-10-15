import json

from echo_commons.modules.reflection.contracts.context import DigestMaterial, SummaryMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind


class SummaryContext:
    def __init__(self, graph, provenance, segments):
        self.graph, self.provenance, self.segments = graph, provenance, segments

    def prepare(self, connection, community_id, character_id, batch_id, graph_kind, now):
        if graph_kind not in {
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            ReflectionGraphKind.MEMORY_ORGANIZE,
        }:
            raise ValueError("Summary context requires a supported summary graph")
        batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
        now = batch.created_at_utc
        rows = self.provenance.batch_summaries(connection, batch)
        materials = []
        if graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            for identity in batch.previous_digest_ids:
                previous = self.provenance.get_digest(
                    connection, community_id, character_id, identity
                )
                materials.append(
                    DigestMaterial(
                        source_id=identity,
                        version=previous["content_version"],
                        content=previous["content"],
                    )
                )
        for row in rows:
            if not row["summary_text"]:
                continue
            segment = self.segments.segments.get(
                connection, community_id, character_id, row["segment_id"]
            )
            materials.append(
                SummaryMaterial(
                    source_id=segment.segment_id,
                    version=segment.summary_version,
                    content=segment.summary_text,
                    started_at_utc=segment.started_at_utc,
                    ended_at_utc=segment.ended_at_utc,
                    conversations=segment.conversations,
                )
            )
        if graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            frozen = connection.execute(
                "SELECT organization_sources_json FROM memory_summary_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()[0]
            if frozen is None:
                raise ValueError("Long-term batch has no original source selection")
            selected = tuple(tuple(item) for item in json.loads(frozen))
            raw = {
                (item.kind, item.source_id, item.version): item
                for row in rows
                for item in self.segments.materials(
                    connection, community_id, character_id, row["segment_id"]
                )
            }
            if set(selected) - raw.keys():
                raise ValueError("Long-term original sources have changed")
            materials.extend(raw[key] for key in selected)
        # 检索背景仍可读取冻结时已有的其他实际经历，整理原文只使用批次的精确引用。
        return self.graph.prepare(
            connection,
            community_id,
            character_id,
            graph_kind,
            "memory_summary_batch",
            batch_id,
            batch.source_version,
            tuple(materials),
            now,
        )
