import json
import sqlite3
from enum import StrEnum

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.views import ViewReadingScope
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import PageOptions, read_page


class MemoryCollection(StrEnum):
    SEGMENTS = "segments"
    DIGESTS = "digests"
    FACTS = "facts"
    COGNITIONS = "cognitions"


QUERIES = {
    MemoryCollection.SEGMENTS: (
        "SELECT segment_id,community_id,character_id,position,started_at_utc,"
        "ended_at_utc,status,source_version,summary_version,sealed_at_utc,"
        "ingested_at_utc,created_at_utc,updated_at_utc FROM memory_segments "
        "WHERE community_id = ? AND character_id = ?",
        "segment_id",
        "created_at_utc",
    ),
    MemoryCollection.DIGESTS: (
        "SELECT d.digest_id,d.batch_id,b.community_id,b.character_id,"
        "d.content_version,d.created_at_utc "
        "FROM memory_digests d JOIN memory_summary_batches b ON b.batch_id = d.batch_id "
        "WHERE b.community_id = ? AND b.character_id = ?",
        "digest_id",
        "created_at_utc",
    ),
    MemoryCollection.FACTS: (
        "SELECT * FROM memory_facts f WHERE community_id=? AND character_id=? "
        "AND version=(SELECT max(version) FROM memory_facts WHERE memory_id=f.memory_id)",
        "memory_id",
        "recorded_at_utc",
    ),
    MemoryCollection.COGNITIONS: (
        "SELECT * FROM memory_cognitions c WHERE community_id=? AND character_id=? "
        "AND version=(SELECT max(version) FROM memory_cognitions WHERE memory_id=c.memory_id)",
        "memory_id",
        "recorded_at_utc",
    ),
}


class MemoryManagement:
    def __init__(self, database: Database) -> None:
        self.database = database

    def core_memory(self, community_id: str, character_id: str) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            current = connection.execute(
                "SELECT content,source_refs_json,supporting_records_json FROM memory_views "
                "WHERE community_id=? AND character_id=? AND view_kind='core_memory'",
                (community_id, character_id),
            ).fetchone()
            latest = connection.execute(
                "SELECT b.materials_json,r.graph_run_id,r.outcome,g.status,g.last_error_code "
                "FROM memory_core_refreshes r JOIN memory_change_batches b USING(batch_id) "
                "LEFT JOIN reflection_graph_runs g USING(graph_run_id) "
                "WHERE b.community_id=? AND b.character_id=? "
                "ORDER BY b.created_at_utc DESC,b.batch_id DESC LIMIT 1",
                (community_id, character_id),
            ).fetchone()
            refresh = None
            if latest:
                request = ViewReadingScope.from_materials(json.loads(latest["materials_json"]))
                refresh = dict(
                    graph_run_id=latest["graph_run_id"],
                    status=latest["status"],
                    error_code=latest["last_error_code"],
                    outcome=latest["outcome"],
                    previous_core=request.previous_core,
                    selected_memory_ids=request.selected_memory_ids,
                    unread_memory_ids=request.unread_memory_ids,
                    processed_count=len(request.processed_versions),
                    total_count=len(request.eligible_versions),
                    sources_readable=request.sources_readable,
                )
            return dict(
                content=current["content"] if current else "",
                source_refs=json.loads(current["source_refs_json"]) if current else [],
                refresh=refresh,
                supporting_records=json.loads(current["supporting_records_json"])
                if current
                else [],
            )

    def index_status(self, community_id: str, character_id: str) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            counts = connection.execute(
                "SELECT COUNT(*) AS documents, "
                "COUNT(v.document_id) AS vectors FROM memory_search_documents d "
                "LEFT JOIN memory_vectors v ON v.document_id=d.document_id "
                "WHERE d.community_id=? AND d.character_id=?",
                (community_id, character_id),
            ).fetchone()
            failures = [
                dict(row)
                for row in connection.execute(
                    "SELECT d.source_kind,d.source_id,x.error_code,"
                    "x.provider_attempts,x.recorded_at_utc "
                    "FROM memory_vector_failures x "
                    "JOIN memory_search_documents d USING(document_id) "
                    "WHERE d.community_id=? AND d.character_id=? "
                    "ORDER BY x.recorded_at_utc DESC LIMIT 50",
                    (community_id, character_id),
                )
            ]
            return dict(counts) | {"failures": failures}

    def list(
        self,
        community_id: str,
        character_id: str,
        collection: MemoryCollection,
        options: PageOptions,
        *,
        conversation_id: str | None = None,
    ) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            sql, identity, timestamp = QUERIES[collection]
            parameters = (community_id, character_id)
            if conversation_id is not None:
                ConversationRepository().get(connection, community_id, conversation_id)
                if collection not in {MemoryCollection.SEGMENTS, MemoryCollection.DIGESTS}:
                    raise ValueError("Conversation filter is available for segments and digests")
                if collection is MemoryCollection.SEGMENTS:
                    sql = (
                        f"SELECT * FROM ({sql}) row WHERE EXISTS (SELECT 1 FROM "
                        "memory_segment_scenes s WHERE s.segment_id=row.segment_id AND "
                        "s.conversation_id=?)"
                    )
                else:
                    sql = (
                        f"SELECT * FROM ({sql}) row WHERE EXISTS (SELECT 1 FROM "
                        "memory_digest_segments d JOIN memory_segment_scenes s USING(segment_id) "
                        "WHERE d.digest_id=row.digest_id AND s.conversation_id=?)"
                    )
                parameters = (*parameters, conversation_id)
            page = read_page(
                connection,
                sql,
                parameters,
                scope={
                    "query": collection.value,
                    "community_id": community_id,
                    "character_id": character_id,
                    "conversation_id": conversation_id,
                },
                order=(timestamp, identity),
                options=options,
            )
            page["items"] = [
                self.scene_values(connection, collection, self.record_values(collection, row))
                for row in page["items"]
            ]
            return page

    def get(
        self, community_id: str, character_id: str, collection: MemoryCollection, identity: str
    ) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            return self.detail(connection, community_id, character_id, collection, identity)

    def detail(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        collection: MemoryCollection,
        identity: str,
        *,
        version: int | None = None,
    ) -> dict:
        sql, key, _ = QUERIES[collection]
        if version is not None:
            table = {
                MemoryCollection.FACTS: "memory_facts",
                MemoryCollection.COGNITIONS: "memory_cognitions",
            }[collection]
            row = connection.execute(
                f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
                f"AND memory_id=? AND version=?",
                (community_id, character_id, identity, version),
            ).fetchone()
        else:
            row = connection.execute(
                f"SELECT * FROM ({sql}) WHERE {key}=?",
                (community_id, character_id, identity),
            ).fetchone()
        if row is None:
            raise NotFoundError("Memory record does not exist in this character scope")
        result = self.scene_values(
            connection, collection, self.record_values(collection, dict(row))
        )
        if collection is MemoryCollection.SEGMENTS:
            result["summary_text"] = connection.execute(
                "SELECT summary_text FROM memory_segments WHERE segment_id = ?",
                (identity,),
            ).fetchone()[0]
            result["sources"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT source_kind,source_id,source_version,ordinal "
                    "FROM memory_segment_sources "
                    "WHERE segment_id = ? ORDER BY ordinal",
                    (identity,),
                )
            ]
            result["context_sources"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT source_kind,source_id,source_version,ordinal FROM "
                    "memory_segment_context "
                    "WHERE segment_id=? ORDER BY ordinal",
                    (identity,),
                )
            ]
            result["consumption"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM memory_organization_consumption WHERE segment_id = ? "
                    "ORDER BY consumed_at_utc",
                    (identity,),
                )
            ]
            result["coverage"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM memory_source_coverage WHERE character_id = ? "
                    "AND owner_kind = 'segment_summary' AND owner_id = ? ORDER BY source_id",
                    (character_id, identity),
                )
            ]
        elif collection is MemoryCollection.DIGESTS:
            result["content"] = connection.execute(
                "SELECT content FROM memory_digests WHERE digest_id = ?",
                (identity,),
            ).fetchone()[0]
            result["batch"] = self.batch(connection, result["batch_id"])
        elif collection in (MemoryCollection.FACTS, MemoryCollection.COGNITIONS):
            result["batch"] = (
                self.batch(connection, result["source_ref"])
                if result["source_kind"] == "memory_summary_batch"
                else None
            )
            kind = "fact" if collection is MemoryCollection.FACTS else "cognition"
            result["sources"] = MemoryProvenanceRepository().record_sources(
                connection, community_id, character_id, kind, identity, result["version"]
            )
            table = "memory_facts" if collection is MemoryCollection.FACTS else "memory_cognitions"
            result["versions"] = [
                {
                    **self.record_values(collection, dict(item)),
                    "sources": MemoryProvenanceRepository().record_sources(
                        connection, community_id, character_id, kind, identity, item["version"]
                    ),
                }
                for item in connection.execute(
                    f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
                    f"AND memory_id=? ORDER BY version DESC",
                    (community_id, character_id, identity),
                )
            ]
            result["stages"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT stage,outcome,completed_at_utc FROM memory_organization_stages "
                    "WHERE character_id=? AND batch_id=? ORDER BY stage",
                    (character_id, result["source_ref"]),
                )
            ]
        return result

    def record_values(self, collection, row):
        result = {"record_kind": collection.value, **row}
        if collection is MemoryCollection.FACTS:
            result["participants"] = json.loads(result.pop("participants_json"))
        elif collection is MemoryCollection.COGNITIONS:
            target = result.pop("target_json")
            result["target"] = json.loads(target) if target else None
        return result

    def batch(self, connection: sqlite3.Connection, batch_id: str) -> dict:
        row = connection.execute(
            "SELECT * FROM memory_summary_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Memory summary batch does not exist")
        return {
            **dict(row),
            "previous_digest_ids": [
                item[0]
                for item in connection.execute(
                    "SELECT digest_id FROM memory_summary_batch_digests WHERE batch_id=? "
                    "ORDER BY ordinal",
                    (batch_id,),
                )
            ],
            "sources": [
                dict(item)
                for item in connection.execute(
                    "SELECT ordinal,segment_id,summary_version FROM memory_summary_batch_items "
                    "WHERE batch_id = ? ORDER BY ordinal",
                    (batch_id,),
                )
            ],
        }

    def scene_values(self, connection, collection, record):
        if collection is MemoryCollection.SEGMENTS:
            record["scenes"] = [
                {
                    "conversation_id": row["conversation_id"],
                    "first_sequence": row["first_sequence"],
                    "last_sequence": row["last_sequence"],
                    "boundary": json.loads(row["boundary_json"]),
                }
                for row in connection.execute(
                    "SELECT * FROM memory_segment_scenes WHERE segment_id=? ORDER BY "
                    "conversation_id",
                    (record["segment_id"],),
                )
            ]
        elif collection is MemoryCollection.DIGESTS:
            record["covered_segments"] = [
                row[0]
                for row in connection.execute(
                    "SELECT segment_id FROM memory_digest_segments WHERE digest_id=? ORDER "
                    "BY segment_id",
                    (record["digest_id"],),
                )
            ]
        return record
