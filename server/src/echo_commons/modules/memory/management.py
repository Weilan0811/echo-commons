import json
import sqlite3
from enum import StrEnum

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.views import ViewReadingScope
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import PageOptions, read_page


class MemoryCollection(StrEnum):
    SEGMENTS = "segments"
    DIGESTS = "digests"
    ENTRIES = "entries"
    ENTITIES = "entities"
    EDGES = "edges"


QUERIES = {
    MemoryCollection.SEGMENTS: (
        "SELECT segment_id,community_id,character_id,conversation_id,first_message_sequence,"
        "last_message_sequence,status,source_version,summary_version,sealed_at_utc,"
        "ingested_at_utc,created_at_utc,updated_at_utc FROM memory_segments "
        "WHERE community_id = ? AND character_id = ?",
        "segment_id",
        "created_at_utc",
    ),
    MemoryCollection.DIGESTS: (
        "SELECT d.digest_id,d.batch_id,b.community_id,b.character_id,b.conversation_id,"
        "d.content_version,d.covers_through_sequence,d.created_at_utc "
        "FROM conversation_digests d JOIN memory_summary_batches b ON b.batch_id = d.batch_id "
        "WHERE b.community_id = ? AND b.character_id = ?",
        "digest_id",
        "created_at_utc",
    ),
    MemoryCollection.ENTRIES: (
        "SELECT memory_id,community_id,character_id,memory_kind,confidence,salience,"
        "source_kind,source_ref,subject_kind,subject_id,visibility,content_version,"
        "occurred_at_utc,recorded_at_utc,expires_at_utc,invalidated_at_utc FROM memory_entries "
        "WHERE community_id = ? AND character_id = ?",
        "memory_id",
        "recorded_at_utc",
    ),
    MemoryCollection.ENTITIES: (
        "SELECT * FROM memory_entities WHERE community_id = ? AND character_id = ?",
        "entity_id",
        "created_at_utc",
    ),
    MemoryCollection.EDGES: (
        "SELECT e.*,i.community_id FROM memory_edges e JOIN character_instances i "
        "ON i.character_id = e.character_id WHERE i.community_id = ? AND e.character_id = ?",
        "edge_id",
        "created_at_utc",
    ),
}


class MemoryManagement:
    def __init__(self, database: Database) -> None:
        self.database = database

    def core_memory(self, community_id: str, character_id: str) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            current = connection.execute(
                "SELECT content,source_refs_json FROM memory_views "
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
                sql = f"SELECT * FROM ({sql}) WHERE conversation_id = ?"
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
            page["items"] = [{"record_kind": collection.value, **row} for row in page["items"]]
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
    ) -> dict:
        sql, key, _ = QUERIES[collection]
        row = connection.execute(
            f"SELECT * FROM ({sql}) WHERE {key} = ?",
            (community_id, character_id, identity),
        ).fetchone()
        if row is None:
            raise NotFoundError("Memory record does not exist in this character scope")
        result = {"record_kind": collection.value, **dict(row)}
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
                "SELECT content FROM conversation_digests WHERE digest_id = ?",
                (identity,),
            ).fetchone()[0]
            result["batch"] = self.batch(connection, result["batch_id"])
        elif collection is MemoryCollection.ENTRIES:
            result["content"] = connection.execute(
                "SELECT content FROM memory_entries WHERE memory_id = ?",
                (identity,),
            ).fetchone()[0]
            result["batch"] = (
                self.batch(connection, result["source_ref"])
                if result["source_kind"] == "memory_summary_batch"
                else None
            )
            result["entities"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT entity_id,role FROM memory_entry_entities WHERE character_id = ? "
                    "AND memory_id = ? ORDER BY entity_id,role",
                    (character_id, identity),
                )
            ]
        elif collection is MemoryCollection.ENTITIES:
            result["aliases"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM memory_entity_aliases WHERE character_id = ? AND entity_id = ? "
                    "ORDER BY created_at_utc,alias_id",
                    (character_id, identity),
                )
            ]
            result["memories"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT memory_id,role FROM memory_entry_entities WHERE character_id = ? "
                    "AND entity_id = ? ORDER BY memory_id,role",
                    (character_id, identity),
                )
            ]
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
            "sources": [
                dict(item)
                for item in connection.execute(
                    "SELECT ordinal,segment_id,summary_version FROM memory_summary_batch_items "
                    "WHERE batch_id = ? ORDER BY ordinal",
                    (batch_id,),
                )
            ],
        }
