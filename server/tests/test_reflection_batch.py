from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from test_reflection_snapshot import _reflection_context, _source_scope

from echo_commons.agents.contracts import CapabilityView, GraphContextSnapshot, ProposalKind
from echo_commons.domain import (
    EvidenceRef,
    GraphSourceRef,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionDependency,
    ReflectionGraphDefinition,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionNodeDefinition,
    ReflectionNodeKind,
    ReflectionNodeTask,
    ReflectionSourceScope,
)
from echo_commons.runtime.reflection import ReflectionBatch

BASE_TIME = datetime(2026, 9, 19, 12, tzinfo=UTC)
NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v1")


def _snapshot() -> GraphContextSnapshot:
    return GraphContextSnapshot.create(
        snapshot_id="snapshot-a",
        account_id="local-player",
        character_id="xiaojin",
        context=_reflection_context(now_utc=BASE_TIME),
        capability_view=CapabilityView(),
        source_scope=_source_scope(),
    )


def _run(snapshot: GraphContextSnapshot) -> ReflectionGraphRun:
    definition = ReflectionGraphDefinition(
        graph_kind=ReflectionGraphKind.SEGMENT_REFLECT,
        version="v1",
        nodes=(
            ReflectionNodeDefinition(
                node_key="segment_summary_plan",
                node_kind=ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
                input_contract="segment_context.v1",
                output_contract=NODE_CONTRACT,
            ),
            ReflectionNodeDefinition(
                node_key="relationship_reflect",
                node_kind=ReflectionNodeKind.RELATIONSHIP_REFLECT,
                input_contract="segment_summary_context.v1",
                output_contract=NODE_CONTRACT,
                required=False,
            ),
        ),
        dependencies=(ReflectionDependency("segment_summary_plan", "relationship_reflect"),),
    )
    return ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=definition,
        account_id="local-player",
        character_id="xiaojin",
        context_snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.snapshot_fingerprint,
        source_scope=ReflectionSourceScope(
            sources=(
                GraphSourceRef(
                    kind="conversation_player",
                    ref="message:1",
                    version="message-v1",
                ),
            )
        ),
        now_utc=BASE_TIME,
    )


def _task(
    run: ReflectionGraphRun, node_key: str, node_kind: ReflectionNodeKind
) -> ReflectionNodeTask:
    return ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_key=node_key,
        node_kind=node_kind,
        dependency_keys=(),
        node_input_fingerprint=f"input:{node_key}",
        output_contract=NODE_CONTRACT,
        now_utc=BASE_TIME,
    )


def _artifact(task: ReflectionNodeTask, payload: dict[str, object]) -> ReflectionArtifact:
    return ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=task.graph_run_id,
        node_task_id=task.task_id,
        attempt=1,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload=payload,
        evidence_refs=(EvidenceRef(kind="source", ref="message:1", version="message-v1"),),
        created_at_utc=BASE_TIME,
    )


def _summary_payload() -> dict[str, object]:
    return {
        "kind": "segment_summary",
        "summary": "摘要",
        "follow_up": {"relationship_reflect": True, "state_reflect": False},
        "evidence_refs": ["message:1"],
    }


def test_batch_aggregates_node_artifacts_in_stable_order() -> None:
    snapshot = _snapshot()
    run = _run(snapshot)
    summary_task = _task(run, "segment_summary_plan", ReflectionNodeKind.SEGMENT_SUMMARY_PLAN)
    relationship_task = _task(run, "relationship_reflect", ReflectionNodeKind.RELATIONSHIP_REFLECT)
    summary = _artifact(summary_task, _summary_payload())
    relationship = _artifact(
        relationship_task,
        {
            "kind": "relationship_reflection",
            "dimensions": [{"dimension": "affection", "direction": "positive", "level": 2}],
            "evidence_refs": ["message:1"],
        },
    )

    first = ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(summary_task, relationship_task),
        artifacts=(relationship, summary),
        snapshot=snapshot,
    )
    second = ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(relationship_task, summary_task),
        artifacts=(summary, relationship),
        snapshot=snapshot,
    )

    assert first.graph_run_id == run.graph_run_id
    assert first.outcome.value == "produced"
    assert len(first.candidates) == 2
    assert len(first.artifact_refs) == 2
    assert first.aggregate_fingerprint == second.aggregate_fingerprint


def test_batch_produces_minimal_graph_review_envelope() -> None:
    snapshot = _snapshot()
    run = _run(snapshot)
    task = _task(run, "segment_summary_plan", ReflectionNodeKind.SEGMENT_SUMMARY_PLAN)
    batch = ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(task,),
        artifacts=(_artifact(task, _summary_payload()),),
        snapshot=snapshot,
    )

    envelope = batch.to_proposal_envelope()

    assert envelope.kind is ProposalKind.REFLECTION_BATCH
    assert envelope.origin.graph_run_id == run.graph_run_id
    assert envelope.payload.candidates == batch.candidates
    assert set(envelope.model_dump()) == {"proposal_id", "kind", "origin", "payload"}


def test_batch_represents_no_op_artifact_with_reason() -> None:
    snapshot = _snapshot()
    run = _run(snapshot)
    task = _task(run, "relationship_reflect", ReflectionNodeKind.RELATIONSHIP_REFLECT)
    artifact = ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=task.graph_run_id,
        node_task_id=task.task_id,
        attempt=1,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload={"kind": "no_op", "reason": "没有新的关系变化", "evidence_refs": []},
        evidence_refs=(),
        created_at_utc=BASE_TIME,
    )

    batch = ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(task,),
        artifacts=(artifact,),
        snapshot=snapshot,
    )

    assert batch.outcome.value == "no_op"
    assert batch.candidates == ()
    assert batch.no_op_reason == "没有新的关系变化"
