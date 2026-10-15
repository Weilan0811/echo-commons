from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_memory_sealing import sealing
from test_message_perspective import build_system, send

from echo_commons.modules.reflection.contracts.candidates import (
    RelationshipDimensionAction,
    RelationshipReflectionAction,
)
from echo_commons.modules.reflection.domain.graph import (
    GraphSourceRef,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionSourceScope,
    content_fingerprint,
    validate_unique_node_tasks,
)
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask, ReflectionNodeTaskStatus
from echo_commons.modules.reflection.domain.rules import (
    RelationshipDimensionProposal,
    normalize_relationship_dimensions,
)
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.validation import DomainInvariantError


def test_registered_topologies_and_scoped_node_recovery(tmp_path):
    system = build_system(tmp_path)
    send(system, "一起玩飞行棋")
    segment = sealing(system).seal("community", "first")
    registry = ReflectionGraphRegistry()
    assert len(registry.definitions) == 4
    assert all(
        item.graph_kind is not ReflectionGraphKind.DIARY_COMPOSE for item in registry.definitions
    )
    definition = registry.require(ReflectionGraphKind.SEGMENT_REFLECT)
    assert definition.required_node_keys == ("segment_summary_plan", "segment_aggregate")
    with pytest.raises(LookupError):
        registry.require(ReflectionGraphKind.SEGMENT_REFLECT, "v2")
    now = datetime.now(UTC)
    fingerprint = content_fingerprint({"sources": segment.source_version})
    graph = ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=definition,
        community_id=segment.community_id,
        character_id=segment.character_id,
        context_snapshot_id=segment.segment_id,
        snapshot_fingerprint=fingerprint,
        source_scope=ReflectionSourceScope(
            tuple(
                GraphSourceRef(source.kind.value, source.source_id, source.version)
                for source in segment.sources
            )
        ),
        now_utc=now,
    )
    root = definition.nodes[0]
    node = ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=graph.graph_run_id,
        node_key=root.node_key,
        node_kind=root.node_kind,
        dependency_keys=(),
        node_input_fingerprint=fingerprint,
        output_contract=root.output_contract,
        now_utc=now,
    )
    graph = graph.register_task(node, now_utc=now).start(now_utc=now)
    assert graph.community_id == "community" and graph.character_id == "first"
    assert validate_unique_node_tasks((node,), graph_run_id=graph.graph_run_id) == (root.node_key,)
    claimed = node.claim(
        worker_id="first-worker", now_utc=now, lease_until_utc=now + timedelta(seconds=1)
    )
    resumed = claimed.apply_recovery(
        worker_id="first-worker",
        now_utc=now + timedelta(seconds=2),
        available_at_utc=now + timedelta(seconds=2),
        error_code="lease_expired",
        target_state=ReflectionNodeTaskStatus.RETRY_WAIT,
        attempt_count=claimed.attempt_count,
        lease_generation=claimed.lease_generation,
        expired=True,
    ).claim(
        worker_id="second-worker",
        now_utc=now + timedelta(seconds=2),
        lease_until_utc=now + timedelta(seconds=3),
    )
    assert (resumed.attempt_count, resumed.lease_generation) == (2, 2)
    assert resumed.node_input_fingerprint == claimed.node_input_fingerprint
    assert not resumed.has_valid_lease(worker_id="first-worker", now_utc=now + timedelta(seconds=2))
    partial = graph.partial(
        now_utc=now + timedelta(seconds=3),
        completed_node_keys=definition.required_node_keys,
        failed_node_keys=("relationship_reflect",),
        skipped_node_keys=("state_reflect",),
    )
    assert partial.status == "partial"


def test_relationship_targets_and_dimension_uniqueness(tmp_path):
    system = build_system(tmp_path)
    with system.database.read() as connection:
        members = {
            member.actor
            for member in system.conversations.conversations.members(connection, "conversation")
        }
    targets = (ActorRef("player", "alice"), ActorRef("character", "second"))
    assert set(targets) <= members
    dimensions = tuple(
        RelationshipDimensionAction(
            target=target, dimension="trust", direction="positive", level=1,
            evidence_refs=("message:actual",)
        )
        for target in targets
    )
    action = RelationshipReflectionAction(
        kind="relationship_reflection", dimensions=dimensions, evidence_refs=("message:source",)
    )
    assert RelationshipReflectionAction.model_validate_json(action.model_dump_json()) == action
    with pytest.raises(ValidationError):
        RelationshipReflectionAction(
            kind="relationship_reflection",
            dimensions=(*dimensions, dimensions[0]),
            evidence_refs=("message:source",),
        )
    proposals = tuple(
        RelationshipDimensionProposal(item.target, item.dimension, item.direction, item.level)
        for item in dimensions
    )
    assert normalize_relationship_dimensions(proposals) == proposals
    with pytest.raises(DomainInvariantError):
        normalize_relationship_dimensions((*proposals, proposals[0]))
