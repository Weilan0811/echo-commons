from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_reflection_snapshot import _reflection_context, _source_scope

from echo_commons.agents.contracts import CapabilityView, GraphContextSnapshot
from echo_commons.domain import (
    DomainInvariantError,
    EvidenceRef,
    OutputContractRef,
    ReflectionArtifact,
)
from echo_commons.runtime.reflection import ReflectionArtifactNormalizer

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


def _artifact(payload: dict[str, object], *, evidence=None) -> ReflectionArtifact:
    return ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=uuid4(),
        node_task_id=uuid4(),
        attempt=1,
        node_input_fingerprint="node-input-v1",
        output_contract=NODE_CONTRACT,
        payload=payload,
        evidence_refs=evidence
        or (EvidenceRef(kind="source", ref="message:1", version="message-v1"),),
        created_at_utc=BASE_TIME,
    )


def _evidence() -> list[str]:
    return ["message:1"]


def test_relationship_artifact_expands_to_one_candidate_per_dimension() -> None:
    artifact = _artifact(
        {
            "kind": "relationship_reflection",
            "dimensions": [
                {"dimension": "affection", "direction": "positive", "level": 2},
                {"dimension": "trust", "direction": "neutral", "level": 0},
            ],
            "evidence_refs": _evidence(),
        }
    )

    result = ReflectionArtifactNormalizer().normalize(
        artifact,
        _snapshot(),
        node_kind="relationship_reflect",
    )

    assert result.outcome.value == "produced"
    assert len(result.candidates) == 2
    assert {candidate.dimension for candidate in result.candidates} == {"affection", "trust"}
    assert all(candidate.source_refs == ("message:1",) for candidate in result.candidates)


def test_graph_artifact_expands_to_entity_and_edge_candidates() -> None:
    artifact = _artifact(
        {
            "kind": "graph_extraction",
            "entities": [
                {"entity_id": "entity:lake", "entity_kind": "place", "canonical_name": "湖"}
            ],
            "edges": [
                {
                    "from_entity_id": "entity:lake",
                    "to_entity_id": "entity:xiaojin",
                    "edge_kind": "near",
                    "confidence": 0.8,
                }
            ],
            "evidence_refs": _evidence(),
        }
    )

    result = ReflectionArtifactNormalizer().normalize(
        artifact,
        _snapshot(),
        node_kind="graph_extract",
    )

    assert [candidate.kind for candidate in result.candidates] == [
        "memory_entity",
        "memory_edge",
    ]


def test_memory_page_artifact_expands_to_multiple_candidates() -> None:
    artifact = _artifact(
        {
            "kind": "long_term_memory_page",
            "pages": [
                {
                    "memory_kind": "promise",
                    "content": "我答应下次告诉对方结果。",
                    "subject_kind": "entity",
                    "subject_id": "promise:result",
                    "confidence": 0.9,
                    "salience": 0.8,
                },
                {
                    "memory_kind": "event",
                    "content": "我记得我们一起完成了那件事。",
                    "subject_kind": "entity",
                    "subject_id": "event:shared-work",
                    "confidence": 0.85,
                    "salience": 0.7,
                },
            ],
            "evidence_refs": _evidence(),
        }
    )

    result = ReflectionArtifactNormalizer().normalize(
        artifact,
        _snapshot(),
        node_kind="page_compose",
    )

    assert len(result.candidates) == 2
    assert [candidate.kind for candidate in result.candidates] == [
        "memory_upsert",
        "memory_upsert",
    ]
    assert [candidate.content for candidate in result.candidates] == [
        "我答应下次告诉对方结果。",
        "我记得我们一起完成了那件事。",
    ]
    assert all(candidate.source_refs == ("message:1",) for candidate in result.candidates)


def test_no_op_artifact_preserves_auditable_reason() -> None:
    artifact = _artifact(
        {
            "kind": "no_op",
            "reason": "本节点没有新的关系变化",
            "evidence_refs": [],
        },
        evidence=(),
    )

    result = ReflectionArtifactNormalizer().normalize(
        artifact,
        _snapshot(),
        node_kind="relationship_reflect",
    )

    assert result.candidates == ()
    assert result.outcome.value == "no_op"
    assert result.no_op_reason == "本节点没有新的关系变化"


def test_normalizer_rejects_stale_evidence_and_wrong_node_action() -> None:
    stale = _artifact(
        {
            "kind": "segment_summary",
            "summary": "摘要",
            "follow_up": {"relationship_reflect": False, "state_reflect": False},
            "evidence_refs": ["message:1"],
        },
        evidence=(EvidenceRef(kind="source", ref="message:1", version="old-version"),),
    )
    with pytest.raises(DomainInvariantError, match="version is stale"):
        ReflectionArtifactNormalizer().normalize(
            stale, _snapshot(), node_kind="segment_summary_plan"
        )

    wrong_node = _artifact(
        {
            "kind": "state_reflection",
            "state_kind": "mood",
            "value": "平静",
            "evidence_refs": _evidence(),
        }
    )
    with pytest.raises(DomainInvariantError, match="not allowed"):
        ReflectionArtifactNormalizer().normalize(
            wrong_node,
            _snapshot(),
            node_kind="relationship_reflect",
        )


def test_core_memory_view_requires_supporting_memory_ids() -> None:
    artifact = _artifact(
        {
            "kind": "view_refresh",
            "view_kind": "core_memory",
            "content": "核心记忆",
            "evidence_refs": _evidence(),
        }
    )

    with pytest.raises(DomainInvariantError, match="supporting memory IDs"):
        ReflectionArtifactNormalizer().normalize(
            artifact,
            _snapshot(),
            node_kind="core_memory_view",
        )
