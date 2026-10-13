import json
from uuid import uuid4

from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.relationship_evidence import (
    RelationshipEvidenceReader,
)
from echo_commons.shared.errors import ConflictError


class ViewInputBudgetExceeded(ConflictError):
    pass


class ViewMaterialPreparation:
    def relationship(self, connection, community, character, fact, now, max_chars):
        content = json.loads(fact["content"])
        content["evidence"] = RelationshipEvidenceReader().read(
            connection,
            community,
            character,
            content["target_kind"],
            content["target_id"],
            now,
            max(0, max_chars - len(fact["content"]) - 64),
        )
        if content["evidence_version"] and not content["evidence"]:
            raise ViewInputBudgetExceeded("Relationship input budget cannot fit evidence")
        target = {"kind": content["target_kind"], "actor_id": content["target_id"]}
        content["long_term_records"] = []
        for row in LongTermMemoryRepository().active_rows(
            connection,
            community,
            character,
            recorded_before=now,
        ):
            matches = (
                (target in json.loads(row["participants_json"]))
                if row["record_kind"] == "fact"
                else (row["target_json"] is not None and json.loads(row["target_json"]) == target)
            )
            if not matches:
                continue
            candidate = dict(
                record_kind=row["record_kind"],
                memory_id=row["memory_id"],
                version=row["version"],
                content=row["content"],
                occurred_at_utc=row["occurred_at_utc"],
            )
            expanded = {**content, "long_term_records": [*content["long_term_records"], candidate]}
            if len(json.dumps(expanded, ensure_ascii=False)) <= max_chars:
                content = expanded
        return {**fact, "content": json.dumps(content, ensure_ascii=False)}

    def missing(self, connection, changes, community, character, now):
        pending = {
            row["source_id"]
            for row in changes.pending(connection, community, character)
            if row["fact_kind"] == "relationship"
        }
        for fact in changes.facts(connection, community, character, now):
            if fact["fact_kind"] != "relationship":
                continue
            if fact["source_id"] in pending:
                continue
            content = json.loads(fact["content"])
            if content["relationship_type"] == "stranger" or not content["initial_description"]:
                continue
            version = f"{fact['version']}:{content['evidence_version']}"
            scheduled = connection.execute(
                "SELECT 1 FROM memory_relationship_refreshes WHERE community_id=? "
                "AND character_id=? AND target_kind=? AND target_id=? AND source_version=?",
                (community, character, content["target_kind"], content["target_id"], version),
            ).fetchone()
            if not scheduled:
                changes.record(
                    connection,
                    community,
                    character,
                    "relationship",
                    fact["source_id"],
                    f"missing:{version}",
                    now,
                )

    def select(
        self,
        connection,
        community,
        character,
        now,
        pending_ids,
        *,
        max_count,
        max_chars,
        batch_id,
        version,
        fresh=False,
    ):
        provenance = MemoryProvenanceRepository()
        rows = LongTermMemoryRepository().active_rows(
            connection,
            community,
            character,
            recorded_before=now,
        )
        by_id = {row["memory_id"]: row for row in rows}
        previous = provenance.view(connection, community, character, "core_memory")
        support = (
            tuple(
                ref.split(":", 1)[1]
                for ref in json.loads(previous["source_refs_json"])
                if ref.startswith("formal_fact:") and ref.split(":", 1)[1] in by_id
            )
            if previous
            else ()
        )
        progress = None if fresh else provenance.progress(connection, community, character)
        eligible = {row["memory_id"]: row["content_version"] for row in rows}
        processed = {
            identity: version
            for identity, version in (progress["processed_versions"] if progress else {}).items()
            if eligible.get(identity) == version
        }
        remaining = [
            row["memory_id"]
            for row in rows
            if processed.get(row["memory_id"]) != row["content_version"]
        ]
        remaining.sort(key=lambda identity: identity not in pending_ids)
        requested = list(dict.fromkeys((*support, *remaining)))
        selected, sources_readable = [], True
        metadata = {
            "selected_memory_ids": [],
            "unread_memory_ids": remaining,
            "processed_versions": dict(processed),
            "eligible_versions": eligible,
            "complete": False,
            "sources_readable": True,
            "previous_core": previous["content"] if previous else "",
        }
        size = 0
        for identity in requested:
            row = by_id[identity]
            references = provenance.record_sources(
                connection, community, character, row["record_kind"], identity, row["version"]
            )
            readable = bool(references) and all(item["readable"] for item in references)
            record = {
                "content": row["content"],
                "record_kind": row["record_kind"],
                "topic": row["topic"],
                "version": row["version"],
                "occurred_at_utc": row["occurred_at_utc"],
                "recorded_at_utc": row["recorded_at_utc"],
                "support_readable": readable,
            }
            content = json.dumps(record, ensure_ascii=False)
            candidate_ids = [item["source_id"] for item in selected] + [identity]
            candidate_metadata = {
                **metadata,
                "selected_memory_ids": candidate_ids,
                "unread_memory_ids": [value for value in remaining if value not in candidate_ids],
                "processed_versions": {
                    **metadata["processed_versions"],
                    identity: row["content_version"],
                },
            }
            candidate_size = (
                size + len(content) + len(json.dumps(candidate_metadata, ensure_ascii=False))
            )
            if len(selected) + 1 >= max_count or candidate_size > max_chars:
                if identity in support or not selected:
                    raise ViewInputBudgetExceeded(
                        "Core memory input budget cannot fit its supporting records"
                    )
                continue
            if not readable:
                raise ConflictError("Core memory supporting material is unavailable")
            selected.append(
                dict(
                    kind="formal_fact",
                    fact_kind=f"memory_{row['record_kind']}",
                    source_id=identity,
                    version=row["content_version"],
                    content=content,
                )
            )
            size += len(content)
            sources_readable = sources_readable and readable
            metadata = candidate_metadata
        selected_ids = {item["source_id"] for item in selected}
        if remaining and not selected_ids.intersection(remaining):
            raise ViewInputBudgetExceeded(
                "Core memory input budget cannot include any unread record"
            )
        metadata.update(
            selected_memory_ids=[item["source_id"] for item in selected],
            unread_memory_ids=[identity for identity in remaining if identity not in selected_ids],
            sources_readable=sources_readable,
        )
        metadata["complete"] = not metadata["unread_memory_ids"]
        selected.append(
            dict(
                kind="formal_fact",
                fact_kind="core_memory_request",
                source_id=batch_id,
                version=version,
                content=json.dumps(metadata, ensure_ascii=False),
            )
        )
        if len(selected) > max_count or sum(len(item["content"]) for item in selected) > max_chars:
            raise ViewInputBudgetExceeded("Core memory selection exceeds its input budget")
        return selected

    def freeze(self, connection, changes, community_id, character_id, now, *, max_count, max_chars):
        self.missing(connection, changes, community_id, character_id, now)
        pending = changes.pending(connection, community_id, character_id)
        continuation = MemoryProvenanceRepository().progress(connection, community_id, character_id)
        if not pending and continuation is None:
            return None
        current = changes.facts(connection, community_id, character_id, now)
        current_ids = {(item["fact_kind"], item["source_id"]) for item in current}
        pending_ids = {(row["fact_kind"], row["source_id"]) for row in pending}
        kinds = {row["fact_kind"] for row in pending}
        core_due = bool(kinds & {"memory_fact", "memory_cognition"}) or continuation is not None
        batch_id = str(uuid4())
        version = str(max(row["change_id"] for row in pending)) if pending else str(uuid4())
        materials, size = [], 0
        relationship_selected = None
        for fact in sorted(
            current, key=lambda item: (item["fact_kind"], item["source_id"]) not in pending_ids
        ):
            if fact["fact_kind"] in ("memory_fact", "memory_cognition"):
                continue
            if fact["fact_kind"] not in kinds:
                continue
            if fact["fact_kind"] == "relationship":
                if (fact["fact_kind"], fact["source_id"]) not in pending_ids:
                    continue
                if relationship_selected is not None:
                    continue
                fact = self.relationship(
                    connection,
                    community_id,
                    character_id,
                    fact,
                    now,
                    max_chars - size,
                )
            if len(materials) >= max_count or size + len(fact["content"]) > max_chars:
                if (fact["fact_kind"], fact["source_id"]) in pending_ids and not materials:
                    raise ConflictError("Formal fact exceeds view input budget")
                continue
            materials.append(fact)
            size += len(fact["content"])
            if fact["fact_kind"] == "relationship":
                relationship_selected = fact["source_id"]
        selected_ids = {(item["fact_kind"], item["source_id"]) for item in materials}
        if core_due:
            try:
                core_materials = self.select(
                    connection,
                    community_id,
                    character_id,
                    now,
                    {
                        source_id
                        for kind, source_id in pending_ids
                        if kind in ("memory_fact", "memory_cognition")
                    },
                    max_count=max_count - len(materials),
                    max_chars=max_chars - size,
                    batch_id=batch_id,
                    version=version,
                )
            except ViewInputBudgetExceeded:
                if not materials:
                    raise
                core_due = False
                core_materials = []
            materials.extend(core_materials)
            selected_ids.update((item["fact_kind"], item["source_id"]) for item in core_materials)
        pending = tuple(
            row
            for row in pending
            if (row["fact_kind"], row["source_id"]) in selected_ids
            or (row["fact_kind"], row["source_id"]) not in current_ids
        )
        if not pending and not core_due:
            return None
        return changes.create_batch(
            connection,
            community_id,
            character_id,
            batch_id,
            version,
            materials,
            pending,
            "automatic" if core_due else None,
            now,
        )
