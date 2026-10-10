import json
from datetime import UTC, datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.views import (
    MemoryViewDraft,
    ViewBranchResult,
    ViewReadingScope,
)
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository


class MemoryViews:
    def read(self, connection, community_id, character_id):
        rows = tuple(
            connection.execute(
                "SELECT * FROM memory_views WHERE community_id=? AND character_id=? "
                "ORDER BY view_kind",
                (community_id, character_id),
            )
        )
        if not rows:
            return ()
        valid = {
            item["source_id"]
            for item in MemoryChangeRepository().facts(
                connection, community_id, character_id, datetime.now(UTC)
            )
        }
        return tuple(
            row
            for row in rows
            if all(
                reference.split(":", 1)[1] in valid
                for reference in json.loads(row["source_refs_json"])
                if reference.startswith("formal_fact:")
            )
        )

    def apply(
        self,
        connection,
        community_id,
        character_id,
        batch_id,
        source_version,
        views: tuple[MemoryViewDraft, ...],
        produced: bool,
        now,
        *,
        view_results: tuple[ViewBranchResult, ...] = (),
    ):
        outcomes = {result.view_kind: result.outcome for result in view_results}
        if "core_memory" in outcomes:
            connection.execute(
                "UPDATE memory_core_refreshes SET outcome=? WHERE batch_id=?",
                (outcomes["core_memory"], batch_id),
            )
        if outcomes.get("core_memory") == "no_op":
            row = connection.execute(
                "SELECT materials_json FROM memory_change_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            request = ViewReadingScope.from_materials(json.loads(row[0]))
            if request and request.complete and request.sources_readable:
                connection.execute(
                    "DELETE FROM memory_views WHERE character_id=? AND view_kind='core_memory'",
                    (character_id,),
                )
        for draft in views:
            existing = connection.execute(
                "SELECT content_version FROM memory_views WHERE character_id=? AND view_kind=?",
                (character_id, draft.kind),
            ).fetchone()
            version = str(int(existing[0]) + 1) if existing else "1"
            connection.execute(
                "INSERT INTO memory_views VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(character_id,view_kind) DO UPDATE SET content=excluded.content,"
                "content_version=excluded.content_version,source_refs_json=excluded.source_refs_json,"
                "source_snapshot_version=excluded.source_snapshot_version,"
                "updated_at_utc=excluded.updated_at_utc",
                (
                    community_id,
                    character_id,
                    draft.kind,
                    draft.content,
                    version,
                    json.dumps(draft.source_refs),
                    source_version,
                    utc_text(now),
                ),
            )
        connection.execute(
            "UPDATE memory_change_batches SET outcome=?,consumed_at_utc=? WHERE batch_id=?",
            ("completed" if produced else "no_op", utc_text(now), batch_id),
        )
