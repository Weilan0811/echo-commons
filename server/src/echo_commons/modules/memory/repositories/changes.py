import json
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
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
                            state_version=state.state_version,
                            evidence_version=connection.execute(
                                "SELECT COUNT(*) FROM relation_evidence WHERE community_id=? "
                                "AND observer_character_id=? AND target_kind=? AND target_id=? "
                                "AND recorded_at_utc<=?",
                                (
                                    community_id,
                                    character_id,
                                    key.target_kind.value,
                                    key.target_id,
                                    utc_text(now),
                                ),
                            ).fetchone()[0],
                            previous_attitude=state.attitude_summary,
                            initial_description=not state.attitude_summary.strip(),
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
            if material["fact_kind"] == "core_memory_request":
                if (material["source_id"], material["version"]) != (
                    batch["batch_id"],
                    batch["source_version"],
                ):
                    raise ConflictError("Core refresh request differs from its frozen batch")
                metadata = json.loads(material["content"])
                eligible = {
                    row["memory_id"]: row["content_version"]
                    for row in MemoryEntryRepository().active_rows(
                        connection,
                        snapshot.scope.community_id,
                        snapshot.scope.character_id,
                        valid_at=datetime.now().astimezone(),
                        recorded_before=datetime.now().astimezone(),
                        include_private=True,
                    )
                }
                if eligible != metadata["eligible_versions"]:
                    raise ConflictError("Core memory reading scope changed")
                continue
            fact = current.get((material["fact_kind"], material["source_id"]))
            if fact is None or fact["version"] != material["version"]:
                raise ConflictError("Memory view facts changed")
            if material["fact_kind"] == "relationship":
                frozen = json.loads(material["content"])
                actual = json.loads(fact["content"])
                if (
                    "evidence_version" in frozen
                    and frozen["evidence_version"] != actual["evidence_version"]
                ):
                    raise ConflictError("Relationship view evidence changed")

    def supersede(self, connection, snapshot, now):
        connection.execute(
            "UPDATE memory_change_batches SET outcome='superseded',consumed_at_utc=? "
            "WHERE batch_id=?",
            (utc_text(now), snapshot.source_id),
        )
        connection.execute(
            "UPDATE memory_changes SET batch_id=NULL WHERE batch_id=?", (snapshot.source_id,)
        )

    def pending(self, connection, community_id, character_id):
        return tuple(
            connection.execute(
                "SELECT * FROM memory_changes WHERE community_id=? AND character_id=? "
                "AND batch_id IS NULL",
                (community_id, character_id),
            )
        )

    def create_batch(
        self,
        connection,
        community,
        character,
        batch_id,
        version,
        materials,
        pending,
        request_kind,
        now,
    ):
        connection.execute(
            "INSERT INTO memory_change_batches VALUES (?,?,?,?,?,NULL,?,NULL)",
            (
                batch_id,
                community,
                character,
                version,
                json.dumps(materials, ensure_ascii=False),
                utc_text(now),
            ),
        )
        connection.executemany(
            "UPDATE memory_changes SET batch_id=? WHERE change_id=?",
            [(batch_id, row["change_id"]) for row in pending],
        )
        if request_kind is not None:
            connection.execute(
                "INSERT INTO memory_core_refreshes(batch_id,request_kind) VALUES (?,?)",
                (batch_id, request_kind),
            )
        for material in materials:
            if material["fact_kind"] != "relationship":
                continue
            content = json.loads(material["content"])
            requests = [
                row
                for row in pending
                if row["fact_kind"] == "relationship" and row["source_id"] == material["source_id"]
            ]
            relationship_request_kind = (
                "missing"
                if requests
                and all(row["source_version"].startswith("missing:") for row in requests)
                else "automatic"
            )
            connection.execute(
                "INSERT INTO memory_relationship_refreshes "
                "(batch_id,community_id,character_id,target_kind,target_id,source_version,"
                "request_kind,error_code,created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    community,
                    character,
                    content["target_kind"],
                    content["target_id"],
                    f"{material['version']}:{content['evidence_version']}",
                    relationship_request_kind,
                    "relationship_evidence_missing" if not content["evidence"] else None,
                    utc_text(now),
                ),
            )
        return self.get(connection, community, character, batch_id)
