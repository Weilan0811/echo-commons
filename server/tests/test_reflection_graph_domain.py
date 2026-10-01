from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from echo_server.domain import (
    ArtifactRef,
    DomainInvariantError,
    EvidenceRef,
    GraphSourceRef,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionDependency,
    ReflectionGraphDefinition,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionGraphRunStatus,
    ReflectionNodeDefinition,
    ReflectionNodeTask,
    ReflectionNodeTaskStatus,
    ReflectionOutcome,
    ReflectionSourceScope,
    RelationshipDimension,
    RelationshipDimensionProposal,
    RelationshipProposalDirection,
    activate_successor,
    content_fingerprint,
    reflection_graph_definition,
    register_artifact,
    validate_no_op,
    validate_reflection_outcome,
    validate_relationship_dimensions,
)

BASE_TIME = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v1")


def source_scope() -> ReflectionSourceScope:
    return ReflectionSourceScope(
        sources=(GraphSourceRef(kind="segment", ref="segment:1", version="segment-v1"),),
    )


def build_definition() -> ReflectionGraphDefinition:
    return ReflectionGraphDefinition(
        graph_kind="test_graph",
        version="v1",
        nodes=(
            ReflectionNodeDefinition(
                node_key="root",
                node_kind="test_root",
                input_contract="snapshot.v1",
                output_contract=NODE_CONTRACT,
            ),
            ReflectionNodeDefinition(
                node_key="child",
                node_kind="test_child",
                input_contract="artifact.v1",
                output_contract=NODE_CONTRACT,
                required=False,
            ),
        ),
        dependencies=(ReflectionDependency("root", "child", "conditional"),),
    )


def build_run() -> ReflectionGraphRun:
    return ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=build_definition(),
        account_id="account",
        character_id="xiaojin",
        context_snapshot_id="snapshot:1",
        snapshot_fingerprint="snapshot-v1",
        source_scope=source_scope(),
        now_utc=BASE_TIME,
    )


def build_task(
    *,
    graph_run_id=None,
    node_key="root",
    dependency_keys=(),
    activated=True,
):
    return ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=graph_run_id or uuid4(),
        node_key=node_key,
        node_kind="test_node",
        dependency_keys=dependency_keys,
        node_input_fingerprint="node-input-v1",
        output_contract=NODE_CONTRACT,
        now_utc=BASE_TIME,
        activated=activated,
    )


def make_artifact(task: ReflectionNodeTask, *, now_utc=BASE_TIME) -> ReflectionArtifact:
    return ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=task.graph_run_id,
        node_task_id=task.task_id,
        attempt=task.attempt_count,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload={"kind": "test", "value": "ok"},
        evidence_refs=(EvidenceRef(kind="segment", ref="segment:1", version="v1"),),
        created_at_utc=now_utc,
    )


def test_fixed_graph_definitions_validate_topology_and_conditional_edges() -> None:
    segment = reflection_graph_definition(ReflectionGraphKind.SEGMENT_REFLECT)
    memory = reflection_graph_definition(ReflectionGraphKind.MEMORY_ORGANIZE)

    assert segment.root_node_keys == ("segment_summary_plan",)
    assert segment.conditional_node_keys == ("relationship_reflect", "state_reflect")
    assert segment.dependencies_satisfied("segment_summary_plan", completed_node_keys=())
    assert not segment.dependencies_satisfied(
        "relationship_reflect",
        completed_node_keys={"segment_summary_plan"},
    )
    assert segment.dependencies_satisfied(
        "relationship_reflect",
        completed_node_keys={"segment_summary_plan"},
        activated_node_keys={"relationship_reflect"},
    )
    assert memory.root_node_keys == ("page_compose", "graph_extract")
    assert set(memory.required_node_keys) == set(memory.node_keys)


def test_graph_definition_rejects_duplicate_unknown_and_cyclic_edges() -> None:
    root = ReflectionNodeDefinition("root", "root", "input.v1", NODE_CONTRACT)
    child = ReflectionNodeDefinition("child", "child", "input.v1", NODE_CONTRACT)
    with pytest.raises(DomainInvariantError, match="node keys must be unique"):
        ReflectionGraphDefinition("test", "v1", (root, root))
    with pytest.raises(DomainInvariantError, match="unknown node"):
        ReflectionGraphDefinition(
            "test",
            "v1",
            (root, child),
            (ReflectionDependency("root", "missing"),),
        )
    with pytest.raises(DomainInvariantError, match="acyclic"):
        ReflectionGraphDefinition(
            "test",
            "v1",
            (root, child),
            (ReflectionDependency("root", "child"), ReflectionDependency("child", "root")),
        )


def test_graph_run_registration_and_completion_are_immutable_and_guarded() -> None:
    run = build_run()
    started = run.start(now_utc=BASE_TIME + timedelta(seconds=1))
    root_task = build_task(graph_run_id=run.graph_run_id, node_key="root")
    registered = started.register_task(root_task, now_utc=BASE_TIME + timedelta(seconds=2))
    with pytest.raises(DomainInvariantError, match="already registered"):
        registered.register_node_key("root")
    with pytest.raises(DomainInvariantError, match="required"):
        registered.complete(
            now_utc=BASE_TIME + timedelta(seconds=3),
            completed_node_keys=(),
        )
    completed = registered.complete(
        now_utc=BASE_TIME + timedelta(seconds=3),
        completed_node_keys={"root"},
    )
    assert completed.status is ReflectionGraphRunStatus.COMPLETED
    assert completed.completed_at_utc == BASE_TIME + timedelta(seconds=3)
    with pytest.raises(FrozenInstanceError):
        completed.status = ReflectionGraphRunStatus.FAILED


def test_graph_run_failure_and_terminal_boundaries() -> None:
    run = build_run().start(now_utc=BASE_TIME + timedelta(seconds=1))
    failed = run.fail(
        now_utc=BASE_TIME + timedelta(seconds=5),
        error_code="node_failed",
    )
    assert failed.status is ReflectionGraphRunStatus.FAILED
    assert failed.is_terminal
    with pytest.raises(DomainInvariantError, match="terminal"):
        failed.cancel(now_utc=BASE_TIME + timedelta(seconds=6))


def test_node_task_requires_dependencies_and_uses_fenced_leases() -> None:
    graph_run_id = uuid4()
    task = build_task(graph_run_id=graph_run_id, node_key="child", dependency_keys=("root",))
    with pytest.raises(DomainInvariantError, match="dependencies"):
        task.claim(
            worker_id="worker-1",
            now_utc=BASE_TIME,
            lease_until_utc=BASE_TIME + timedelta(seconds=10),
        )
    claimed = task.claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=10),
        completed_node_keys={"root"},
    )
    assert claimed.status is ReflectionNodeTaskStatus.PROCESSING
    assert claimed.attempt_count == 1
    assert claimed.lease_generation == 1
    artifact = make_artifact(claimed)
    completed = claimed.complete(
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=1),
        artifact=artifact,
        attempt_count=1,
        lease_generation=1,
    )
    assert completed.artifact_id == artifact.artifact_id
    with pytest.raises(DomainInvariantError, match="pending"):
        completed.claim(
            worker_id="worker-2",
            now_utc=BASE_TIME + timedelta(seconds=2),
            lease_until_utc=BASE_TIME + timedelta(seconds=12),
            completed_node_keys={"root"},
        )


def test_expired_node_lease_cannot_complete_or_activate_successor() -> None:
    graph_run_id = uuid4()
    predecessor = build_task(graph_run_id=graph_run_id, node_key="root").claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=5),
    )
    successor = build_task(
        graph_run_id=graph_run_id,
        node_key="child",
        dependency_keys=("root",),
        activated=False,
    )
    with pytest.raises(DomainInvariantError, match="expired"):
        predecessor.complete(
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=5),
            artifact=uuid4(),
            attempt_count=1,
            lease_generation=1,
        )
    with pytest.raises(DomainInvariantError, match="completed predecessor"):
        activate_successor(
            successor,
            predecessor,
            now_utc=BASE_TIME + timedelta(seconds=5),
        )


def test_successful_artifact_is_content_checked_and_idempotently_registered() -> None:
    task = build_task().claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=5),
    )
    artifact = make_artifact(task)
    assert artifact.reference == ArtifactRef(artifact.artifact_id, artifact.content_fingerprint)
    assert artifact.payload == {"kind": "test", "value": "ok"}
    assert content_fingerprint({"a": 1}) == content_fingerprint({"a": 1})
    assert content_fingerprint({"a": 1}) != content_fingerprint({"a": 2})
    assert register_artifact(None, artifact) is artifact
    assert register_artifact(artifact, artifact) is artifact
    with pytest.raises(DomainInvariantError, match="fingerprint"):
        ReflectionArtifact(
            artifact_id=artifact.artifact_id,
            graph_run_id=artifact.graph_run_id,
            node_task_id=artifact.node_task_id,
            attempt=artifact.attempt,
            node_input_fingerprint=artifact.node_input_fingerprint,
            output_contract=NODE_CONTRACT,
            payload={"kind": "changed"},
            evidence_refs=artifact.evidence_refs,
            created_at_utc=artifact.created_at_utc,
            content_fingerprint=artifact.content_fingerprint,
        )
    with pytest.raises(DomainInvariantError, match="immutable"):
        register_artifact(
            artifact,
            ReflectionArtifact.create(
                artifact_id=artifact.artifact_id,
                graph_run_id=artifact.graph_run_id,
                node_task_id=artifact.node_task_id,
                attempt=artifact.attempt,
                node_input_fingerprint=artifact.node_input_fingerprint,
                output_contract=NODE_CONTRACT,
                payload={"kind": "different"},
                evidence_refs=artifact.evidence_refs,
                created_at_utc=artifact.created_at_utc,
            ),
        )


def test_relationship_dimensions_are_bounded_and_distinct() -> None:
    values = validate_relationship_dimensions(
        (
            RelationshipDimensionProposal(
                RelationshipDimension.AFFECTION,
                RelationshipProposalDirection.POSITIVE,
                2,
            ),
            {"dimension": "trust", "direction": "neutral", "level": 0},
        )
    )
    assert values[0].dimension is RelationshipDimension.AFFECTION
    assert values[1].direction is RelationshipProposalDirection.NEUTRAL
    with pytest.raises(DomainInvariantError, match="unique"):
        validate_relationship_dimensions(
            (
                {"dimension": "trust", "direction": "positive", "level": 1},
                {"dimension": "trust", "direction": "negative", "level": 1},
            )
        )
    with pytest.raises(DomainInvariantError, match="level 0"):
        RelationshipDimensionProposal("attachment", "neutral", 1)


def test_reflection_no_op_requires_explicit_reason_and_empty_output() -> None:
    assert validate_no_op("  no meaningful change  ") == "no meaningful change"
    decision = validate_reflection_outcome(
        ReflectionOutcome.PRODUCED,
        produced_items=("artifact",),
    )
    assert decision.no_op_reason is None
    with pytest.raises(DomainInvariantError, match="no-op reason"):
        validate_no_op(" ")
    with pytest.raises(DomainInvariantError, match="must not contain items"):
        validate_no_op("nothing", produced_items=("unexpected",))
    with pytest.raises(DomainInvariantError, match="must contain items"):
        validate_reflection_outcome(ReflectionOutcome.PRODUCED)
