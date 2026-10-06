import json
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.shared.errors import ConflictError


class MemoryChangeRepository:
    def facts(self, connection, community_id, character_id, now):
        facts = []
        for row in connection.execute(
            "SELECT * FROM memory_entries WHERE community_id=? AND character_id=? "
            "AND invalidated_at_utc IS NULL AND (expires_at_utc IS NULL OR expires_at_utc>?) "
            "ORDER BY salience DESC,recorded_at_utc DESC,memory_id",
            (community_id, character_id, utc_text(now)),
        ):
            facts.append(
                dict(
                    kind="formal_fact",
                    fact_kind="memory_entry",
                    source_id=row["memory_id"],
                    version=row["content_version"],
                    content=row["content"],
                )
            )
        states = StateRepository()
        for kind in StateKind:
            entry = states.latest(connection, character_id, kind, now)
            if entry is None or not entry.value.strip():
                continue
            facts.append(
                dict(
                    kind="formal_fact",
                    fact_kind="character_state",
                    source_id=entry.entry_id,
                    version=str(entry.state_version),
                    content=f"{kind.value}：{entry.value}",
                )
            )
        relationships = RelationshipRepository()
        for key in relationships.keys(connection, community_id, character_id):
            state = relationships.get(connection, key, now)
            facts.append(
                dict(
                    kind="formal_fact",
                    fact_kind="relationship",
                    source_id=f"{character_id}/{key.target_kind.value}/{key.target_id}",
                    version=str(state.state_version),
                    content=json.dumps(
                        dict(
                            target_kind=key.target_kind.value,
                            target_id=key.target_id,
                            relationship_type=state.relationship_type.value,
                            affection=state.values.affection if state.values else None,
                            trust=state.values.trust if state.values else None,
                            attachment=state.values.attachment if state.values else None,
                        ),
                        ensure_ascii=False,
                    ),
                )
            )
        return tuple(facts)

    def record(self, connection, community_id, character_id, fact_kind, source_id, version, now):
        connection.execute(
            "INSERT INTO memory_changes (community_id,character_id,fact_kind,source_id,"
            "source_version,created_at_utc) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (community_id, character_id, fact_kind, source_id, str(version), utc_text(now)),
        )

    def freeze(self, connection, community_id, character_id, now, *, max_count, max_chars):
        pending = tuple(
            connection.execute(
                "SELECT * FROM memory_changes WHERE community_id=? AND character_id=? "
                "AND batch_id IS NULL",
                (community_id, character_id),
            )
        )
        if not pending:
            return None
        current = self.facts(connection, community_id, character_id, now)
        current_ids = {(item["fact_kind"], item["source_id"]) for item in current}
        pending_ids = {(row["fact_kind"], row["source_id"]) for row in pending}
        kinds = {row["fact_kind"] for row in pending}
        materials, size = [], 0
        relationship_selected = None
        for fact in sorted(
            current, key=lambda item: (item["fact_kind"], item["source_id"]) not in pending_ids
        ):
            if fact["fact_kind"] not in kinds:
                continue
            if fact["fact_kind"] == "relationship":
                if (fact["fact_kind"], fact["source_id"]) not in pending_ids:
                    continue
                if relationship_selected is not None:
                    continue
            if len(materials) >= max_count or size + len(fact["content"]) > max_chars:
                if (fact["fact_kind"], fact["source_id"]) in pending_ids and not materials:
                    raise ConflictError("Formal fact exceeds view input budget")
                continue
            materials.append(fact)
            size += len(fact["content"])
            if fact["fact_kind"] == "relationship":
                relationship_selected = fact["source_id"]
        selected_ids = {(item["fact_kind"], item["source_id"]) for item in materials}
        pending = tuple(
            row
            for row in pending
            if (row["fact_kind"], row["source_id"]) in selected_ids
            or (row["fact_kind"], row["source_id"]) not in current_ids
        )
        if not pending:
            return None
        batch_id = str(uuid4())
        version = str(max(row["change_id"] for row in pending))
        connection.execute(
            "INSERT INTO memory_change_batches VALUES (?,?,?,?,?,NULL,?,NULL)",
            (
                batch_id,
                community_id,
                character_id,
                version,
                json.dumps(materials, ensure_ascii=False),
                utc_text(now),
            ),
        )
        connection.executemany(
            "UPDATE memory_changes SET batch_id=? WHERE change_id=?",
            [(batch_id, row["change_id"]) for row in pending],
        )
        return self.get(connection, community_id, character_id, batch_id)

    def get(self, connection, community_id, character_id, batch_id):
        row = connection.execute(
            "SELECT * FROM memory_change_batches WHERE community_id=? "
            "AND character_id=? AND batch_id=?",
            (community_id, character_id, batch_id),
        ).fetchone()
        if row is None:
            raise ConflictError("Memory change batch is unavailable")
        return row

    def check(self, connection, snapshot):
        batch = self.get(
            connection, snapshot.scope.community_id, snapshot.scope.character_id, snapshot.source_id
        )
        if batch["source_version"] != snapshot.source_version:
            raise ConflictError("Memory change version differs")
        current = {
            (item["fact_kind"], item["source_id"]): item
            for item in self.facts(
                connection,
                snapshot.scope.community_id,
                snapshot.scope.character_id,
                datetime.now().astimezone(),
            )
        }
        for material in json.loads(batch["materials_json"]):
            fact = current.get((material["fact_kind"], material["source_id"]))
            if fact is None or fact["version"] != material["version"]:
                raise ConflictError("Memory view facts changed")

    def supersede(self, connection, snapshot, now):
        connection.execute(
            "UPDATE memory_change_batches SET outcome='superseded',consumed_at_utc=? "
            "WHERE batch_id=?",
            (utc_text(now), snapshot.source_id),
        )
        connection.execute(
            "UPDATE memory_changes SET batch_id=NULL WHERE batch_id=?", (snapshot.source_id,)
        )
