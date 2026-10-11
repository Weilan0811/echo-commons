import json
from uuid import uuid4

from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.relationship_evidence import (
    RelationshipEvidenceReader,
)
from echo_commons.shared.errors import ConflictError


class ViewInputBudgetExceeded(ConflictError):
    pass


class ViewMaterialPreparation:
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
        rows = MemoryEntryRepository().active_rows(
            connection,
            community,
            character,
            valid_at=now,
            recorded_before=now,
            include_private=True,
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
        source_cache = {}
        provided_sources = {}
        metadata = {
            "selected_memory_ids": [],
            "unread_memory_ids": remaining,
            "processed_versions": dict(processed),
            "eligible_versions": eligible,
            "complete": False,
            "sources_readable": True,
            "previous_core": previous["content"] if previous else "",
        }
        reserve = len(json.dumps(metadata, ensure_ascii=False)) + len(requested) * 80 + 300
        size = reserve
        for identity in requested:
            row = by_id[identity]
            source = (row["source_kind"], row["source_ref"])
            if source not in source_cache:
                source_cache[source] = provenance.support(connection, community, character, row)
            evidence, readable = source_cache[source]
            page = {
                "content": row["content"],
                "memory_kind": row["memory_kind"],
                "source_kind": row["source_kind"],
                "source_ref": row["source_ref"],
                "recorded_at_utc": row["recorded_at_utc"],
                "supporting_materials": [] if source in provided_sources else evidence,
                "support_in_memory_id": provided_sources.get(source),
                "support_readable": readable,
            }
            content = json.dumps(page, ensure_ascii=False)
            if len(selected) + 1 >= max_count or size + len(content) > max_chars:
                if identity in support or not selected:
                    raise ViewInputBudgetExceeded(
                        "Core memory input budget cannot fit its supporting pages"
                    )
                continue
            if not readable:
                raise ConflictError("Core memory supporting material is unavailable")
            selected.append(
                dict(
                    kind="formal_fact",
                    fact_kind="memory_entry",
                    source_id=identity,
                    version=row["content_version"],
                    content=content,
                )
            )
            size += len(content)
            provided_sources[source] = identity
            sources_readable = sources_readable and readable
            metadata["processed_versions"][identity] = row["content_version"]
        selected_ids = {item["source_id"] for item in selected}
        if remaining and not selected_ids.intersection(remaining):
            raise ViewInputBudgetExceeded("Core memory input budget cannot include any unread page")
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
        pending = changes.pending(connection, community_id, character_id)
        continuation = MemoryProvenanceRepository().progress(connection, community_id, character_id)
        if not pending and continuation is None:
            return None
        current = changes.facts(connection, community_id, character_id, now)
        current_ids = {(item["fact_kind"], item["source_id"]) for item in current}
        pending_ids = {(row["fact_kind"], row["source_id"]) for row in pending}
        kinds = {row["fact_kind"] for row in pending}
        core_due = "memory_entry" in kinds or continuation is not None
        batch_id = str(uuid4())
        version = str(max(row["change_id"] for row in pending)) if pending else str(uuid4())
        materials, size = [], 0
        relationship_selected = None
        for fact in sorted(
            current, key=lambda item: (item["fact_kind"], item["source_id"]) not in pending_ids
        ):
            if fact["fact_kind"] == "memory_entry":
                continue
            if fact["fact_kind"] not in kinds:
                continue
            if fact["fact_kind"] == "relationship":
                if (fact["fact_kind"], fact["source_id"]) not in pending_ids:
                    continue
                if relationship_selected is not None:
                    continue
                content = json.loads(fact["content"])
                # 为证据列表和 JSON 分隔符保留空间，证据正文与正式事实共用材料预算。
                content["evidence"] = RelationshipEvidenceReader().read(
                    connection,
                    community_id,
                    character_id,
                    content["target_kind"],
                    content["target_id"],
                    now,
                    max(0, max_chars - size - len(fact["content"]) - 64),
                )
                fact = {**fact, "content": json.dumps(content, ensure_ascii=False)}
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
                    {source_id for kind, source_id in pending_ids if kind == "memory_entry"},
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
