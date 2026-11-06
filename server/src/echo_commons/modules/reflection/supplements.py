import json
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.organization import MemoryFactContent, MemoryRecordRef
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryFactCandidate,
    MemoryFactReviewAction,
    ReflectionBatchProposal,
    SavedFactReadout,
)
from echo_commons.modules.reflection.domain.graph import ReflectionArtifact, ReflectionGraphKind
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
from echo_commons.shared.errors import ConflictError


def supplement(coordinator, connection, original, now):
    if original.graph_kind not in {
        ReflectionGraphKind.SEGMENT_REFLECT,
        ReflectionGraphKind.VIEW_REFRESH,
        ReflectionGraphKind.MEMORY_ORGANIZE,
    }:
        raise ConflictError("This graph requires atomic recovery")
    child = connection.execute(
        "SELECT r.graph_run_id FROM reflection_supplements s "
        "JOIN reflection_graph_runs r USING(graph_run_id) WHERE s.original_run_id=? "
        "ORDER BY s.created_at_utc DESC LIMIT 1",
        (str(original.graph_run_id),),
    ).fetchone()
    if child:
        existing = coordinator.runs.get(
            connection, original.community_id, original.character_id, child[0]
        )
        if not existing.is_terminal or existing.status == "completed":
            return existing
    previous = coordinator.nodes.for_graph(connection, str(original.graph_run_id))
    failed = {node.node_key for node in previous if node.status == "failed"}
    if not failed:
        raise ConflictError("Partial graph has no failed branches")
    snapshot = coordinator.runs.snapshot(
        connection, original.community_id, original.character_id, str(original.graph_run_id)
    )
    if original.graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
        raw = tuple(item for item in snapshot.materials if item.kind != "formal_fact")
        snapshot = coordinator.context.graph.prepare(
            connection,
            original.community_id,
            original.character_id,
            snapshot.graph_kind,
            snapshot.source_kind,
            snapshot.source_id,
            snapshot.source_version,
            raw,
            now,
            conversations=snapshot.conversations,
        )
    coordinator.context.sources.check_sources(connection, snapshot)
    run = coordinator.start_snapshot_in(connection, snapshot, now)
    connection.execute(
        "INSERT INTO reflection_supplements VALUES (?,?,?,?)",
        (
            str(run.graph_run_id),
            str(original.graph_run_id),
            json.dumps(sorted(failed)),
            utc_text(now),
        ),
    )
    connection.execute(
        "UPDATE memory_relationship_refreshes SET graph_run_id=? WHERE graph_run_id=?",
        (str(run.graph_run_id), str(original.graph_run_id)),
    )
    repository = ArtifactRepository()
    definition = coordinator.registry.require(run.graph_kind)
    by_key = {node.node_key: node for node in previous}
    for node in coordinator.nodes.for_graph(connection, str(run.graph_run_id)):
        if node.node_key == definition.aggregate_node_key:
            continue
        if node.node_key in failed:
            coordinator.nodes.save(
                connection, node.activate(now_utc=now) if not node.activated else node
            )
        elif by_key[node.node_key].status == "completed":
            old = repository.get(
                connection, str(original.graph_run_id), str(by_key[node.node_key].artifact_id)
            )
            payload = old.payload.to_dict()
            if (
                original.graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE
                and node.node_key == "fact_review"
            ):
                approved = MemoryFactReviewAction.model_validate(payload)
                phase = connection.execute(
                    "SELECT references_json FROM memory_organization_stages WHERE community_id=? "
                    "AND character_id=? AND batch_id=? AND stage='facts'",
                    (original.community_id, original.character_id, snapshot.source_id),
                ).fetchone()
                if phase is None:
                    raise ConflictError("Saved fact phase is unavailable")
                saved = []
                for value in json.loads(phase[0]).values():
                    ref = MemoryRecordRef.model_validate(value)
                    row = LongTermMemoryRepository().get(
                        connection, original.community_id, original.character_id, ref
                    )
                    sources = MemoryProvenanceRepository(
                        coordinator.context.perspective.activities
                    ).record_sources(
                        connection,
                        original.community_id,
                        original.character_id,
                        "fact",
                        ref.memory_id,
                        ref.version,
                    )
                    if (
                        row["status"] not in ("current", "superseded")
                        or not sources
                        or not all(item["readable"] for item in sources)
                    ):
                        raise ConflictError("Saved fact phase requires valid original support")
                    saved.append(
                        SavedFactReadout(
                            reference=ref,
                            fact=MemoryFactContent(
                                topic=row["topic"],
                                content=row["content"],
                                participants=json.loads(row["participants_json"]),
                                occurred_at_utc=row["occurred_at_utc"],
                                conditions=row["conditions"],
                                salience=row["salience"],
                            ),
                        )
                    )
                candidates = tuple(
                    MemoryFactCandidate(source_refs=fact.evidence_refs, operation=fact)
                    for fact in approved.facts
                )
                used = (
                    ReflectionBatchProposal(candidates=candidates).content_chars
                    if candidates
                    else approved.used_content_chars
                )
                payload = MemoryFactReviewAction(
                    saved_facts=tuple(saved),
                    evidence_refs=approved.evidence_refs,
                    used_candidates=len(candidates) if candidates else approved.used_candidates,
                    used_content_chars=used,
                ).model_dump(mode="json")
            artifact = ReflectionArtifact.create(
                artifact_id=uuid4(),
                graph_run_id=run.graph_run_id,
                node_task_id=node.task_id,
                attempt=old.attempt,
                node_input_fingerprint=node.node_input_fingerprint,
                output_contract=node.output_contract,
                payload=payload,
                evidence_refs=old.evidence_refs,
                created_at_utc=now,
            )
            repository.add(
                connection,
                artifact,
                {
                    "reused_artifact_id": str(old.artifact_id),
                    "original_run_id": str(original.graph_run_id),
                },
            )
            coordinator.nodes.save(connection, node.reuse_completed(artifact, now_utc=now))
        else:
            coordinator.nodes.save(
                connection, node.skip(now_utc=now, reason_code="original_branch_skipped")
            )
    bind_ready_inputs(
        connection, str(run.graph_run_id), now, coordinator.runs, coordinator.nodes, repository
    )
    return run
