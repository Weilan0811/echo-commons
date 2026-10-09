import json
import sqlite3

from echo_commons.modules.maintenance.contracts import (
    CleanupBlocker,
    CleanupRequest,
    CleanupResult,
)

# 社群权威数据直接按所属社群选择；共享人物资源和玩家需要明确指定。
COMMUNITY_TABLES = (
    "communities",
    "community_members",
    "character_instances",
    "character_state_entries",
    "conversations",
    "conversation_memberships",
    "input_batches",
    "social_turns",
    "conversation_tasks",
    "messages",
    "relation_evidence",
    "relationship_state",
    "memory_segments",
    "memory_entries",
    "thoughts",
    "memory_source_coverage",
    "memory_summary_batches",
    "diary_entries",
    "memory_views",
    "memory_entities",
    "memory_search_documents",
    "reflection_graph_runs",
    "task_execution_events",
    "memory_author_batches",
    "memory_changes",
    "memory_change_batches",
    "social_chains",
    "realtime_events",
)
RELATED_TABLES = {
    "social_turn_batches": ("social_turn_id", "social_turns", "social_turn_id"),
    "participation_decisions": ("social_turn_id", "social_turns", "social_turn_id"),
    "social_candidates": ("social_turn_id", "social_turns", "social_turn_id"),
    "social_triggers": ("input_batch_id", "input_batches", "input_batch_id"),
    "conversation_results": ("task_id", "conversation_tasks", "task_id"),
    "message_mentions": ("message_id", "messages", "message_id"),
    "message_recipients": ("message_id", "messages", "message_id"),
    "input_batch_messages": ("input_batch_id", "input_batches", "input_batch_id"),
    "memory_segment_sources": ("segment_id", "memory_segments", "segment_id"),
    "memory_summary_batch_items": ("batch_id", "memory_summary_batches", "batch_id"),
    "conversation_digests": ("batch_id", "memory_summary_batches", "batch_id"),
    "memory_organization_consumption": ("segment_id", "memory_segments", "segment_id"),
    "memory_entity_aliases": ("character_id", "character_instances", "character_id"),
    "memory_entry_entities": ("character_id", "character_instances", "character_id"),
    "memory_edges": ("character_id", "character_instances", "character_id"),
    "reflection_node_tasks": ("graph_run_id", "reflection_graph_runs", "graph_run_id"),
    "reflection_artifacts": ("graph_run_id", "reflection_graph_runs", "graph_run_id"),
    "reflection_graph_results": ("graph_run_id", "reflection_graph_runs", "graph_run_id"),
    "reflection_supplements": ("graph_run_id", "reflection_graph_runs", "graph_run_id"),
    "conversation_read_positions": ("conversation_id", "conversations", "conversation_id"),
    "conversation_membership_operations": ("conversation_id", "conversations", "conversation_id"),
    "memory_author_materials": ("character_id", "character_instances", "character_id"),
    "memory_author_chunks": ("material_id", "memory_author_materials", "material_id"),
    "memory_initializations": ("character_id", "character_instances", "character_id"),
    "memory_vectors": ("document_id", "memory_search_documents", "document_id"),
    "memory_vector_failures": ("document_id", "memory_search_documents", "document_id"),
    "memory_organization_entities": ("character_id", "character_instances", "character_id"),
    "character_authoring_candidates": ("draft_id", "character_authoring_drafts", "draft_id"),
    "custom_character_blueprints": ("source_draft_id", "character_authoring_drafts", "draft_id"),
}
TABLES = (
    *COMMUNITY_TABLES,
    "character_authoring_drafts",
    "players",
    *RELATED_TABLES,
    "trace_outbox",
    "traces",
    "memory_search_fts",
)


def selected(table: str, column: str = "rowid") -> str:
    return (
        f"SELECT {column} FROM {table} WHERE rowid IN "
        f"(SELECT row_id FROM cleanup_scope WHERE table_name='{table}')"
    )


class CleanupRepository:
    def preview(self, connection: sqlite3.Connection, request: CleanupRequest) -> CleanupResult:
        connection.execute(
            "CREATE TEMP TABLE cleanup_scope "
            "(table_name TEXT NOT NULL,row_id INTEGER NOT NULL,PRIMARY KEY(table_name,row_id))"
        )
        parameters = {
            "communities": json.dumps(request.community_ids),
            "drafts": json.dumps(request.draft_ids),
            "players": json.dumps(request.player_ids),
        }
        for table in COMMUNITY_TABLES:
            self._select(
                connection,
                table,
                "community_id IN (SELECT value FROM json_each(:communities))",
                parameters,
            )
        for table, column, scope in (
            ("character_authoring_drafts", "draft_id", "drafts"),
            ("players", "player_id", "players"),
        ):
            self._select(
                connection,
                table,
                f"{column} IN (SELECT value FROM json_each(:{scope}))",
                parameters,
            )
        for table, (column, parent, parent_column) in RELATED_TABLES.items():
            self._select(connection, table, f"{column} IN ({selected(parent, parent_column)})")
        correlations = " UNION ".join(
            selected(table, "trace_id")
            for table in ("conversation_tasks", "reflection_graph_runs", "messages")
        )
        correlations += " UNION " + selected("messages", "message_id")
        for table in ("trace_outbox", "traces"):
            self._select(
                connection,
                table,
                "json_extract(payload_json,'$.community_id') IN "
                f"({selected('communities', 'community_id')}) "
                f"OR correlation_id IN ({correlations})",
            )
        self._select(
            connection,
            "memory_search_fts",
            f"rowid IN ({selected('memory_search_documents', 'document_id')})",
        )
        counts = {
            table: connection.execute(
                "SELECT COUNT(*) FROM cleanup_scope WHERE table_name=?", (table,)
            ).fetchone()[0]
            for table in TABLES
        }
        missing = {}
        for key, table, column, ids in (
            ("community_ids", "communities", "community_id", request.community_ids),
            ("draft_ids", "character_authoring_drafts", "draft_id", request.draft_ids),
            ("player_ids", "players", "player_id", request.player_ids),
        ):
            found = {row[0] for row in connection.execute(selected(table, column))}
            missing[key] = sorted(set(ids) - found)
        return CleanupResult(
            dry_run=request.dry_run,
            counts=counts,
            missing=missing,
            blockers=self._blockers(connection),
        )

    def _select(self, connection, table, predicate, parameters=()):
        connection.execute(
            f"INSERT INTO cleanup_scope SELECT '{table}',rowid FROM {table} WHERE {predicate}",
            parameters,
        )

    def _blockers(self, connection) -> list[CleanupBlocker]:
        checks = [
            (
                "community",
                "communities",
                "community_id",
                "status <> 'paused'",
                "社群必须暂停后才能清理",
            ),
            (
                "conversation_task",
                "conversation_tasks",
                "task_id",
                "status='processing'",
                "回复任务正在执行",
            ),
            (
                "reflection_node",
                "reflection_node_tasks",
                "node_task_id",
                "status='processing'",
                "记忆任务正在执行",
            ),
            (
                "authoring_candidate",
                "character_authoring_candidates",
                "candidate_id",
                "status='processing'",
                "人物创作请求正在执行",
            ),
            ("trace", "trace_outbox", "trace_id", "status='processing'", "追踪正在投递"),
        ]
        blockers = []
        for kind, table, column, condition, reason in checks:
            for row in connection.execute(
                f"SELECT {column} FROM {table} WHERE rowid IN ({selected(table)}) AND {condition}"
            ):
                blockers.append(CleanupBlocker(kind=kind, object_id=row[0], reason=reason))
        for row in connection.execute(
            "SELECT character_id FROM character_instances WHERE blueprint_id IN "
            f"({selected('custom_character_blueprints', 'blueprint_id')}) AND rowid NOT IN "
            f"({selected('character_instances')})"
        ):
            blockers.append(
                CleanupBlocker(
                    kind="character",
                    object_id=row[0],
                    reason="范围外角色仍使用所选草稿的固定人物资源",
                )
            )
        for table, column, condition, reason in (
            ("community_members", "actor_id", "actor_kind='player'", "玩家仍属于范围外社群"),
            ("character_authoring_drafts", "owner_player_id", "1", "玩家仍拥有未选择的草稿"),
            (
                "custom_character_blueprints",
                "owner_player_id",
                "1",
                "玩家仍拥有未选择的固定人物资源",
            ),
            ("conversation_read_positions", "player_id", "1", "玩家仍有范围外会话的阅读记录"),
        ):
            for row in connection.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {condition} AND {column} IN "
                f"({selected('players', 'player_id')}) AND rowid NOT IN ({selected(table)})"
            ):
                blockers.append(CleanupBlocker(kind="player", object_id=row[0], reason=reason))
        return blockers

    def delete(self, connection):
        # 延迟检查循环外键，提交时仍要求所有关联完整；范围在删除前已经固定。
        connection.execute("PRAGMA defer_foreign_keys=ON")
        for table in reversed(TABLES):
            connection.execute(
                f"DELETE FROM {table} WHERE rowid IN "
                "(SELECT row_id FROM cleanup_scope WHERE table_name=?)",
                (table,),
            )
