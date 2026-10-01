from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from echo_commons.agents.contracts import (
    ContinuityDigestCandidate,
    MemoryEdgeCandidate,
    MemoryEntityCandidate,
    MemoryUpsertCandidate,
    ProposalEnvelope,
    ReflectionBatchProposal,
    ReflectionGraphOrigin,
    RelationshipImpactCandidate,
    SegmentSummaryCandidate,
    StateEntryCandidate,
)
from echo_commons.agents.contracts.reflection_graph import GraphContextSnapshot
from echo_commons.app.settings import Settings
from echo_commons.domain.errors import DomainInvariantError
from echo_commons.domain.memory import MemorySegment, MemorySegmentStatus
from echo_commons.domain.memory_sources import SummaryBatch
from echo_commons.domain.proposals import ProposalDecision
from echo_commons.domain.reflection_graph import ReflectionGraphKind, ReflectionGraphRun
from echo_commons.domain.reflection_rules import ReflectionOutcome
from echo_commons.runtime.reflection.batch import ReflectionBatch


class ReflectionReviewCode(StrEnum):
    APPROVED = "approved"
    INVALID_PAYLOAD = "invalid_payload"
    GRAPH_MISMATCH = "graph_mismatch"
    SOURCE_MISMATCH = "source_mismatch"
    UNSUPPORTED_CANDIDATE = "unsupported_candidate"
    SUMMARY_REQUIRED = "nonempty_segment_requires_summary"
    SUMMARY_BOUNDARY = "segment_summary_boundary_mismatch"
    SEGMENT_NOT_READY = "reflection_segment_not_ready"
    TOO_MANY_CANDIDATES = "reflection_batch_too_large"
    OUTPUT_TOO_LARGE = "reflection_batch_output_too_large"
    MEMORY_BATCH_MISMATCH = "memory_organization_batch_mismatch"
    CONTINUITY_BATCH_MISMATCH = "continuity_compression_batch_mismatch"
    CONTINUITY_DIGEST_REQUIRED = "continuity_compression_requires_digest"
    CONTINUITY_BOUNDARY = "continuity_digest_boundary_mismatch"


@dataclass(frozen=True, slots=True)
class SegmentReflectionChangeSet:
    """Only the reviewed facts that the segment flow may write."""

    segment_id: UUID
    summary: SegmentSummaryCandidate | None
    relationship_impacts: tuple[RelationshipImpactCandidate, ...] = ()
    state_entries: tuple[StateEntryCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, UUID):
            raise DomainInvariantError("segment_id must be a UUID")
        relationships = tuple(self.relationship_impacts)
        states = tuple(self.state_entries)
        if any(not isinstance(item, RelationshipImpactCandidate) for item in relationships):
            raise DomainInvariantError("change set contains an invalid relationship fact")
        if any(not isinstance(item, StateEntryCandidate) for item in states):
            raise DomainInvariantError("change set contains an invalid state fact")
        if self.summary is not None and not isinstance(self.summary, SegmentSummaryCandidate):
            raise DomainInvariantError("change set summary is invalid")
        if len({item.dimension for item in relationships}) != len(relationships):
            raise DomainInvariantError("change set relationship dimensions must be unique")
        if len({item.state_kind for item in states}) != len(states):
            raise DomainInvariantError("change set state kinds must be unique")
        object.__setattr__(self, "relationship_impacts", relationships)
        object.__setattr__(self, "state_entries", states)


@dataclass(frozen=True, slots=True)
class MemoryOrganizationChangeSet:
    """经过审核、等待 Runtime 解析实体身份的记忆候选。"""

    batch_id: str
    memory_entries: tuple[MemoryUpsertCandidate, ...] = ()
    entities: tuple[MemoryEntityCandidate, ...] = ()
    edges: tuple[MemoryEdgeCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise DomainInvariantError("memory organization change set requires batch_id")
        memory_entries = tuple(self.memory_entries)
        entities = tuple(self.entities)
        edges = tuple(self.edges)
        if any(not isinstance(item, MemoryUpsertCandidate) for item in memory_entries):
            raise DomainInvariantError("change set contains an invalid memory entry")
        if any(not isinstance(item, MemoryEntityCandidate) for item in entities):
            raise DomainInvariantError("change set contains an invalid memory entity")
        if any(not isinstance(item, MemoryEdgeCandidate) for item in edges):
            raise DomainInvariantError("change set contains an invalid memory edge")
        object.__setattr__(self, "memory_entries", memory_entries)
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "edges", edges)


@dataclass(frozen=True, slots=True)
class ContinuityCompressionChangeSet:
    """经过审核、等待 Runtime 写入会话连续性摘要的候选。"""

    batch_id: str
    digest: ContinuityDigestCandidate

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise DomainInvariantError("continuity change set requires batch_id")
        if not isinstance(self.digest, ContinuityDigestCandidate):
            raise DomainInvariantError("change set digest is invalid")


@dataclass(frozen=True, slots=True)
class ReviewedReflectionBatch:
    """Review decision kept with the graph batch until ChangeSet construction."""

    batch: ReflectionBatch
    decision: ProposalDecision
    code: ReflectionReviewCode | str
    change_set: (
        SegmentReflectionChangeSet
        | MemoryOrganizationChangeSet
        | ContinuityCompressionChangeSet
        | None
    ) = None

    def __post_init__(self) -> None:
        if not isinstance(self.batch, ReflectionBatch):
            raise DomainInvariantError("reviewed batch requires a ReflectionBatch")
        object.__setattr__(self, "decision", ProposalDecision(self.decision))
        object.__setattr__(self, "code", ReflectionReviewCode(self.code))

    @property
    def approved(self) -> bool:
        return self.decision is ProposalDecision.APPROVED

    def with_change_set(
        self,
        change_set: (
            SegmentReflectionChangeSet
            | MemoryOrganizationChangeSet
            | ContinuityCompressionChangeSet
        ),
    ) -> ReviewedReflectionBatch:
        if not self.approved:
            raise DomainInvariantError("a rejected ReflectionBatch cannot receive a ChangeSet")
        return replace(self, change_set=change_set)


def _validate_common_batch(
    envelope: ProposalEnvelope,
    *,
    batch: ReflectionBatch,
    graph_run: ReflectionGraphRun,
    snapshot: GraphContextSnapshot,
    graph_kind: ReflectionGraphKind,
    max_candidates: int,
    max_output_chars: int,
) -> ReflectionReviewCode | None:
    if envelope.kind.value != "reflection_batch" or not isinstance(
        envelope.payload, ReflectionBatchProposal
    ):
        return ReflectionReviewCode.INVALID_PAYLOAD
    if not isinstance(envelope.origin, ReflectionGraphOrigin):
        return ReflectionReviewCode.GRAPH_MISMATCH
    if (
        envelope.origin.graph_run_id != graph_run.graph_run_id
        or batch.graph_run_id != graph_run.graph_run_id
        or graph_run.graph_kind is not graph_kind
    ):
        return ReflectionReviewCode.GRAPH_MISMATCH
    if envelope.payload.candidates != batch.candidates:
        return ReflectionReviewCode.INVALID_PAYLOAD
    if envelope.payload.outcome.value != batch.outcome.value:
        return ReflectionReviewCode.INVALID_PAYLOAD
    if envelope.payload.no_op_reason != batch.no_op_reason:
        return ReflectionReviewCode.INVALID_PAYLOAD
    candidates = batch.candidates
    if len(candidates) > max_candidates:
        return ReflectionReviewCode.TOO_MANY_CANDIDATES
    if sum(len(candidate.model_dump_json()) for candidate in candidates) > max_output_chars:
        return ReflectionReviewCode.OUTPUT_TOO_LARGE
    source_refs = set(snapshot.source_refs)
    if any(not set(candidate.source_refs) <= source_refs for candidate in candidates):
        return ReflectionReviewCode.SOURCE_MISMATCH
    return None


class ReflectionReviewer:
    """Review graph output against its frozen source boundary."""

    _SEGMENT_CANDIDATES = (
        SegmentSummaryCandidate,
        RelationshipImpactCandidate,
        StateEntryCandidate,
    )
    _MEMORY_CANDIDATES = (
        MemoryUpsertCandidate,
        MemoryEntityCandidate,
        MemoryEdgeCandidate,
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def review(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
    ) -> ReviewedReflectionBatch:
        code = self._validate(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            segment=segment,
        )
        return ReviewedReflectionBatch(
            batch=batch,
            decision=(
                ProposalDecision.APPROVED
                if code is ReflectionReviewCode.APPROVED
                else ProposalDecision.REJECTED
            ),
            code=code,
        )

    def _validate(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
    ) -> ReflectionReviewCode:
        common_code = _validate_common_batch(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            graph_kind=ReflectionGraphKind.SEGMENT_REFLECT,
            max_candidates=self.settings.reflection_max_candidates,
            max_output_chars=self.settings.reflection_max_output_chars,
        )
        if common_code is not None:
            return common_code
        if segment.status not in {MemorySegmentStatus.SEALED, MemorySegmentStatus.INGESTED}:
            return ReflectionReviewCode.SEGMENT_NOT_READY
        if (
            segment.account_id != graph_run.account_id
            or segment.character_id != graph_run.character_id
        ):
            return ReflectionReviewCode.SOURCE_MISMATCH
        segment_source = next(
            (
                source
                for source in graph_run.source_scope.sources
                if source.kind == "memory_segment" and source.ref == str(segment.segment_id)
            ),
            None,
        )
        if segment_source is None or segment_source.version != segment.source_version:
            return ReflectionReviewCode.SOURCE_MISMATCH

        candidates = batch.candidates
        if any(not isinstance(candidate, self._SEGMENT_CANDIDATES) for candidate in candidates):
            return ReflectionReviewCode.UNSUPPORTED_CANDIDATE

        summaries = [
            candidate for candidate in candidates if isinstance(candidate, SegmentSummaryCandidate)
        ]
        if batch.outcome is ReflectionOutcome.NO_OP:
            if snapshot.has_window_material:
                return ReflectionReviewCode.SUMMARY_REQUIRED
            if candidates:
                return ReflectionReviewCode.INVALID_PAYLOAD
            return ReflectionReviewCode.APPROVED
        if not snapshot.has_window_material or len(summaries) != 1:
            return ReflectionReviewCode.SUMMARY_REQUIRED
        summary = summaries[0]
        if (
            summary.first_message_sequence != segment.first_message_sequence
            or summary.last_message_sequence != segment.last_message_sequence
        ):
            return ReflectionReviewCode.SUMMARY_BOUNDARY
        return ReflectionReviewCode.APPROVED

    def review_memory_organization(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
    ) -> ReviewedReflectionBatch:
        code = self._validate_memory_organization(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            summary_batch=summary_batch,
        )
        return ReviewedReflectionBatch(
            batch=batch,
            decision=(
                ProposalDecision.APPROVED
                if code is ReflectionReviewCode.APPROVED
                else ProposalDecision.REJECTED
            ),
            code=code,
        )

    def review_continuity_compression(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
    ) -> ReviewedReflectionBatch:
        code = self._validate_continuity_compression(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            summary_batch=summary_batch,
        )
        return ReviewedReflectionBatch(
            batch=batch,
            decision=(
                ProposalDecision.APPROVED
                if code is ReflectionReviewCode.APPROVED
                else ProposalDecision.REJECTED
            ),
            code=code,
        )

    def _validate_continuity_compression(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
    ) -> ReflectionReviewCode:
        common_code = _validate_common_batch(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            graph_kind=ReflectionGraphKind.CONTINUITY_COMPRESS,
            max_candidates=self.settings.reflection_max_candidates,
            max_output_chars=self.settings.reflection_max_output_chars,
        )
        if common_code is not None:
            return common_code
        batch_source = next(
            (
                source
                for source in graph_run.source_scope.sources
                if source.kind == "memory_summary_batch" and source.ref == summary_batch.batch_id
            ),
            None,
        )
        if (
            batch_source is None
            or batch_source.version != summary_batch.source_version
            or summary_batch.account_id != graph_run.account_id
            or summary_batch.character_id != graph_run.character_id
        ):
            return ReflectionReviewCode.CONTINUITY_BATCH_MISMATCH
        if not snapshot.context.materials:
            return ReflectionReviewCode.CONTINUITY_DIGEST_REQUIRED
        candidates = batch.candidates
        if any(not isinstance(candidate, ContinuityDigestCandidate) for candidate in candidates):
            return ReflectionReviewCode.UNSUPPORTED_CANDIDATE
        if batch.outcome is ReflectionOutcome.NO_OP or len(candidates) != 1:
            return ReflectionReviewCode.CONTINUITY_DIGEST_REQUIRED
        digest = candidates[0]
        last_sequence = snapshot.context.window.last_message_sequence
        if digest.covers_through_sequence != last_sequence:
            return ReflectionReviewCode.CONTINUITY_BOUNDARY
        return ReflectionReviewCode.APPROVED

    def _validate_memory_organization(
        self,
        envelope: ProposalEnvelope,
        *,
        batch: ReflectionBatch,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
    ) -> ReflectionReviewCode:
        common_code = _validate_common_batch(
            envelope,
            batch=batch,
            graph_run=graph_run,
            snapshot=snapshot,
            graph_kind=ReflectionGraphKind.MEMORY_ORGANIZE,
            max_candidates=self.settings.reflection_max_candidates,
            max_output_chars=self.settings.reflection_max_output_chars,
        )
        if common_code is not None:
            return common_code
        batch_source = next(
            (
                source
                for source in graph_run.source_scope.sources
                if source.kind == "memory_summary_batch" and source.ref == summary_batch.batch_id
            ),
            None,
        )
        if (
            batch_source is None
            or batch_source.version != summary_batch.source_version
            or summary_batch.account_id != graph_run.account_id
            or summary_batch.character_id != graph_run.character_id
        ):
            return ReflectionReviewCode.MEMORY_BATCH_MISMATCH
        candidates = batch.candidates
        if any(not isinstance(candidate, self._MEMORY_CANDIDATES) for candidate in candidates):
            return ReflectionReviewCode.UNSUPPORTED_CANDIDATE
        entity_keys = {
            candidate.entity_id
            for candidate in candidates
            if isinstance(candidate, MemoryEntityCandidate)
        }
        if any(
            candidate.from_entity_id not in entity_keys or candidate.to_entity_id not in entity_keys
            for candidate in candidates
            if isinstance(candidate, MemoryEdgeCandidate)
        ):
            return ReflectionReviewCode.UNSUPPORTED_CANDIDATE
        if batch.outcome is ReflectionOutcome.NO_OP and candidates:
            return ReflectionReviewCode.INVALID_PAYLOAD
        return ReflectionReviewCode.APPROVED


class ChangeSetBuilder:
    """Project an approved batch into its Runtime-owned change set."""

    def build(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        segment_id: UUID,
    ) -> ReviewedReflectionBatch:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can build a ChangeSet")
        candidates = reviewed.batch.candidates
        if reviewed.batch.outcome is ReflectionOutcome.NO_OP:
            change_set = SegmentReflectionChangeSet(segment_id=segment_id, summary=None)
            return reviewed.with_change_set(change_set)
        summaries = tuple(item for item in candidates if isinstance(item, SegmentSummaryCandidate))
        relationships = tuple(
            item for item in candidates if isinstance(item, RelationshipImpactCandidate)
        )
        states = tuple(item for item in candidates if isinstance(item, StateEntryCandidate))
        if len(summaries) != 1:
            raise DomainInvariantError("nonempty_segment_requires_summary")
        return reviewed.with_change_set(
            SegmentReflectionChangeSet(
                segment_id=segment_id,
                summary=summaries[0],
                relationship_impacts=relationships,
                state_entries=states,
            )
        )

    def build_memory(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        batch_id: str,
    ) -> ReviewedReflectionBatch:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can build a ChangeSet")
        candidates = reviewed.batch.candidates
        if reviewed.batch.outcome is ReflectionOutcome.NO_OP:
            return reviewed.with_change_set(MemoryOrganizationChangeSet(batch_id=batch_id))
        return reviewed.with_change_set(
            MemoryOrganizationChangeSet(
                batch_id=batch_id,
                memory_entries=tuple(
                    item for item in candidates if isinstance(item, MemoryUpsertCandidate)
                ),
                entities=tuple(
                    item for item in candidates if isinstance(item, MemoryEntityCandidate)
                ),
                edges=tuple(item for item in candidates if isinstance(item, MemoryEdgeCandidate)),
            )
        )

    def build_continuity(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        batch_id: str,
    ) -> ReviewedReflectionBatch:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can build a ChangeSet")
        candidates = reviewed.batch.candidates
        digests = tuple(item for item in candidates if isinstance(item, ContinuityDigestCandidate))
        if reviewed.batch.outcome is ReflectionOutcome.NO_OP or len(digests) != 1:
            raise DomainInvariantError("continuity_compression_requires_digest")
        return reviewed.with_change_set(
            ContinuityCompressionChangeSet(batch_id=batch_id, digest=digests[0])
        )


__all__ = [
    "ChangeSetBuilder",
    "ContinuityCompressionChangeSet",
    "ReflectionReviewCode",
    "ReflectionReviewer",
    "ReviewedReflectionBatch",
    "MemoryOrganizationChangeSet",
    "SegmentReflectionChangeSet",
]
