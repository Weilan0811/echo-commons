from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from test_reflection_snapshot import _reflection_context, _source_scope

from echo_server.agents.contracts import (
    CapabilityView,
    GraphContextSnapshot,
    GraphSourceReference,
    GraphSourceScope,
    ReflectionGraphOrigin,
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_server.config import Settings
from echo_server.domain import (
    EvidenceRef,
    GraphSourceRef,
    MemorySegment,
    MemorySegmentStatus,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionNodeKind,
    ReflectionNodeTask,
    ReflectionSourceScope,
)
from echo_server.domain.memory_sources import MemorySourceKind, MemorySourceRef, SummaryBatch
from echo_server.domain.reflection_graph import reflection_graph_definition
from echo_server.runtime.reflection import (
    ChangeSetBuilder,
    ReflectionBatch,
    ReflectionReviewCode,
    ReflectionReviewer,
)

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


def _segment(*, first: int = 1, last: int = 1) -> MemorySegment:
    return MemorySegment(
        segment_id=uuid4(),
        account_id="local-player",
        conversation_id="xiaojin",
        character_id="xiaojin",
        first_message_sequence=first,
        last_message_sequence=last,
        status=MemorySegmentStatus.SEALED,
        source_version="segment-v1",
        sealed_at_utc=BASE_TIME,
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )


def _continuity_snapshot() -> GraphContextSnapshot:
    context = _reflection_context(now_utc=BASE_TIME).model_copy(
        update={
            "window": ReflectionWindowContext(
                first_message_sequence=1,
                last_message_sequence=2,
            ),
            "materials": (
                ReflectionSourceMaterial(
                    source_ref="summary:segment-1",
                    source_kind="memory_segment_summary",
                    content="对话摘要",
                    content_version="summary-v1",
                ),
            ),
        }
    )
    return GraphContextSnapshot.create(
        snapshot_id="continuity-snapshot",
        account_id="local-player",
        character_id="xiaojin",
        context=context,
        capability_view=CapabilityView(),
        source_scope=GraphSourceScope(
            sources=(
                GraphSourceReference(
                    kind="memory_summary_batch",
                    ref="batch-1",
                    version="batch-v1",
                ),
                GraphSourceReference(
                    kind="memory_segment_summary",
                    ref="summary:segment-1",
                    version="summary-v1",
                ),
            )
        ),
    )


def _continuity_run(snapshot: GraphContextSnapshot) -> ReflectionGraphRun:
    return ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=reflection_graph_definition(ReflectionGraphKind.CONTINUITY_COMPRESS),
        account_id="local-player",
        character_id="xiaojin",
        context_snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.snapshot_fingerprint,
        source_scope=ReflectionSourceScope(
            sources=(
                GraphSourceRef(
                    kind="memory_summary_batch",
                    ref="batch-1",
                    version="batch-v1",
                ),
                GraphSourceRef(
                    kind="memory_segment_summary",
                    ref="summary:segment-1",
                    version="summary-v1",
                ),
            )
        ),
        now_utc=BASE_TIME,
    )


def _continuity_batch(
    snapshot: GraphContextSnapshot,
    run: ReflectionGraphRun,
    *,
    covers_through_sequence: int = 2,
    no_op: bool = False,
) -> ReflectionBatch:
    task = ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_key="continuity_compress",
        node_kind=ReflectionNodeKind.CONTINUITY_COMPRESS,
        dependency_keys=(),
        node_input_fingerprint="node-input-v1",
        output_contract=NODE_CONTRACT,
        now_utc=BASE_TIME,
    )
    artifact = ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_task_id=task.task_id,
        attempt=1,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload=(
            {"kind": "no_op", "reason": "没有新的连续性内容", "evidence_refs": []}
            if no_op
            else {
                "kind": "continuity_digest",
                "content": "我记得这段交流。",
                "covers_through_sequence": covers_through_sequence,
                "evidence_refs": ["summary:segment-1"],
            }
        ),
        evidence_refs=()
        if no_op
        else (EvidenceRef(kind="source", ref="summary:segment-1", version="summary-v1"),),
        created_at_utc=BASE_TIME,
    )
    return ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(task,),
        artifacts=(artifact,),
        snapshot=snapshot,
    )


def _run(snapshot: GraphContextSnapshot, segment: MemorySegment) -> ReflectionGraphRun:
    return ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=reflection_graph_definition(ReflectionGraphKind.SEGMENT_REFLECT),
        account_id="local-player",
        character_id="xiaojin",
        context_snapshot_id=snapshot.snapshot_id,
        snapshot_fingerprint=snapshot.snapshot_fingerprint,
        source_scope=ReflectionSourceScope(
            sources=(
                GraphSourceRef(
                    kind="memory_segment",
                    ref=str(segment.segment_id),
                    version=segment.source_version,
                ),
                GraphSourceRef(
                    kind="conversation_player",
                    ref="message:1",
                    version="message-v1",
                ),
            )
        ),
        now_utc=BASE_TIME,
    )


def _batch(
    snapshot: GraphContextSnapshot,
    run: ReflectionGraphRun,
    *,
    no_op: bool = False,
) -> ReflectionBatch:
    task = ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_key="segment_summary_plan",
        node_kind=ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
        dependency_keys=(),
        node_input_fingerprint="node-input-v1",
        output_contract=NODE_CONTRACT,
        now_utc=BASE_TIME,
    )
    artifact = ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_task_id=task.task_id,
        attempt=1,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload=(
            {"kind": "no_op", "reason": "没有新的摘要", "evidence_refs": []}
            if no_op
            else {
                "kind": "segment_summary",
                "summary": "对话摘要",
                "follow_up": {"relationship_reflect": True, "state_reflect": False},
                "evidence_refs": ["message:1"],
            }
        ),
        evidence_refs=()
        if no_op
        else (EvidenceRef(kind="source", ref="message:1", version="message-v1"),),
        created_at_utc=BASE_TIME,
    )
    return ReflectionBatch.from_artifacts(
        graph_run=run,
        node_tasks=(task,),
        artifacts=(artifact,),
        snapshot=snapshot,
    )


def test_reviewer_approves_graph_batch_and_builds_fact_change_set() -> None:
    snapshot = _snapshot()
    segment = _segment()
    run = _run(snapshot, segment)
    batch = _batch(snapshot, run)

    reviewed = ReflectionReviewer(Settings()).review(
        batch.to_proposal_envelope(),
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        segment=segment,
    )
    reviewed = ChangeSetBuilder().build(reviewed, segment_id=segment.segment_id)

    assert reviewed.approved
    assert reviewed.code is ReflectionReviewCode.APPROVED
    assert reviewed.change_set is not None
    assert reviewed.change_set.summary is not None
    assert reviewed.change_set.segment_id == segment.segment_id


def test_reviewer_uses_graph_origin_and_segment_scope_as_identity() -> None:
    snapshot = _snapshot()
    segment = _segment()
    run = _run(snapshot, segment)
    batch = _batch(snapshot, run)
    envelope = batch.to_proposal_envelope().model_copy(
        update={"origin": ReflectionGraphOrigin(graph_run_id=uuid4())}
    )

    reviewed = ReflectionReviewer(Settings()).review(
        envelope,
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        segment=segment,
    )

    assert not reviewed.approved
    assert reviewed.code is ReflectionReviewCode.GRAPH_MISMATCH


def test_reviewer_rejects_summary_with_stale_segment_boundary() -> None:
    snapshot = _snapshot()
    segment = _segment(first=2, last=2)
    run = _run(snapshot, segment)
    batch = _batch(snapshot, run)

    reviewed = ReflectionReviewer(Settings()).review(
        batch.to_proposal_envelope(),
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        segment=segment,
    )

    assert reviewed.decision.value == "rejected"
    assert reviewed.code is ReflectionReviewCode.SUMMARY_BOUNDARY


def test_reviewer_rejects_no_op_for_a_nonempty_segment() -> None:
    snapshot = _snapshot()
    segment = _segment()
    run = _run(snapshot, segment)
    batch = _batch(snapshot, run, no_op=True)

    reviewed = ReflectionReviewer(Settings()).review(
        batch.to_proposal_envelope(),
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        segment=segment,
    )

    assert not reviewed.approved
    assert reviewed.code is ReflectionReviewCode.SUMMARY_REQUIRED


def test_reviewer_uses_configured_candidate_limit() -> None:
    snapshot = _snapshot()
    segment = _segment()
    run = _run(snapshot, segment)
    batch = _batch(snapshot, run)

    reviewed = ReflectionReviewer(Settings(reflection_max_candidates=0)).review(
        batch.to_proposal_envelope(),
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        segment=segment,
    )

    assert not reviewed.approved
    assert reviewed.code is ReflectionReviewCode.TOO_MANY_CANDIDATES


def test_reviewer_approves_continuity_digest_with_batch_boundary() -> None:
    snapshot = _continuity_snapshot()
    run = _continuity_run(snapshot)
    batch = _continuity_batch(snapshot, run)
    summary_batch = SummaryBatch(
        batch_id="batch-1",
        account_id="local-player",
        conversation_id="xiaojin",
        character_id="xiaojin",
        sources=(
            MemorySourceRef(
                MemorySourceKind.SEGMENT_SUMMARY,
                "segment-1",
                "summary-v1",
            ),
        ),
        source_version="batch-v1",
        previous_digest_id=None,
    )

    reviewed = ReflectionReviewer(Settings()).review_continuity_compression(
        batch.to_proposal_envelope(),
        batch=batch,
        graph_run=run,
        snapshot=snapshot,
        summary_batch=summary_batch,
    )
    reviewed = ChangeSetBuilder().build_continuity(reviewed, batch_id=summary_batch.batch_id)

    assert reviewed.approved
    assert reviewed.code is ReflectionReviewCode.APPROVED
    assert reviewed.change_set is not None
    assert reviewed.change_set.digest.covers_through_sequence == 2


def test_reviewer_rejects_continuity_digest_boundary_and_no_op() -> None:
    snapshot = _continuity_snapshot()
    run = _continuity_run(snapshot)
    summary_batch = SummaryBatch(
        batch_id="batch-1",
        account_id="local-player",
        conversation_id="xiaojin",
        character_id="xiaojin",
        sources=(
            MemorySourceRef(
                MemorySourceKind.SEGMENT_SUMMARY,
                "segment-1",
                "summary-v1",
            ),
        ),
        source_version="batch-v1",
        previous_digest_id=None,
    )

    boundary_batch = _continuity_batch(snapshot, run, covers_through_sequence=1)
    boundary = ReflectionReviewer(Settings()).review_continuity_compression(
        boundary_batch.to_proposal_envelope(),
        batch=boundary_batch,
        graph_run=run,
        snapshot=snapshot,
        summary_batch=summary_batch,
    )
    assert not boundary.approved
    assert boundary.code is ReflectionReviewCode.CONTINUITY_BOUNDARY

    no_op_batch = _continuity_batch(snapshot, run, no_op=True)
    no_op = ReflectionReviewer(Settings()).review_continuity_compression(
        no_op_batch.to_proposal_envelope(),
        batch=no_op_batch,
        graph_run=run,
        snapshot=snapshot,
        summary_batch=summary_batch,
    )
    assert not no_op.approved
    assert no_op.code is ReflectionReviewCode.CONTINUITY_DIGEST_REQUIRED
