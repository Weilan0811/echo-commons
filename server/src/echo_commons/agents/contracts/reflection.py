"""Versioned reflection batch payloads produced by Character Agents.

Reflection is deliberately represented as one Runtime Proposal. The candidate
models below describe the small, typed vocabulary that the Runtime can review
later; they do not grant an Agent any write access or persistence identity.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReflectionCandidateKind(StrEnum):
    """Typed candidate shapes carried inside one reflection batch."""

    SEGMENT_SUMMARY = "segment_summary"
    MEMORY_UPSERT = "memory_upsert"
    DIARY_APPEND = "diary_append"
    CORE_MEMORY_REWRITE = "core_memory_rewrite"
    VIEW_REWRITE = "view_rewrite"
    STATE_ENTRY = "state_entry"
    RELATIONSHIP_IMPACT = "relationship_impact"
    ENTITY_ALIAS = "entity_alias"
    MEMORY_EDGE = "memory_edge"
    MEMORY_ENTITY = "memory_entity"
    CONTINUITY_DIGEST = "continuity_digest"


class ReflectionBatchOutcome(StrEnum):
    """Whether a graph produced candidates for the final review batch."""

    PRODUCED = "produced"
    NO_OP = "no_op"


class ReflectionNodeActionKind(StrEnum):
    """Provider-neutral action vocabulary for one reflection node."""

    SEGMENT_SUMMARY = "segment_summary"
    RELATIONSHIP_REFLECTION = "relationship_reflection"
    STATE_REFLECTION = "state_reflection"
    CONTINUITY_DIGEST = "continuity_digest"
    LONG_TERM_MEMORY_PAGE = "long_term_memory_page"
    GRAPH_EXTRACTION = "graph_extraction"
    DIARY = "diary"
    VIEW_REFRESH = "view_refresh"
    NO_OP = "no_op"


class FollowUpDecision(BaseModel):
    """Route request returned by the segment summary node.

    The two flags only request the fixed follow-up nodes.  They do not state
    that a relationship or state fact has already changed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship_reflect: bool
    state_reflect: bool


def _normalize_source_refs(value: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(item.strip() for item in value if item.strip())
    if not normalized:
        raise ValueError("source_refs must contain at least one non-empty reference")
    if len(normalized) != len(set(normalized)):
        raise ValueError("source_refs must not contain duplicates")
    return normalized


class EvidenceRef(BaseModel):
    """Runtime-owned typed evidence identity for node inputs and Artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=100)
    ref: str = Field(min_length=1, max_length=300)
    version: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def references_must_contain_text(self) -> EvidenceRef:
        if not self.kind.strip() or not self.ref.strip():
            raise ValueError("evidence reference kind and ref must contain text")
        return self


def _normalize_model_evidence_refs(value: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(item.strip() for item in value if item.strip())
    if len(normalized) != len(set(normalized)):
        raise ValueError("evidence_refs must not contain duplicates")
    return normalized


class ReflectionCandidateBase(BaseModel):
    """Common provenance required by every reflection candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_refs: tuple[str, ...] = Field(min_length=1, max_length=32)

    @field_validator("source_refs")
    @classmethod
    def source_refs_must_be_named(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_source_refs(value)


class SegmentSummaryCandidate(ReflectionCandidateBase):
    kind: Literal["segment_summary"] = ReflectionCandidateKind.SEGMENT_SUMMARY.value
    summary: str = Field(min_length=1, max_length=4000)
    first_message_sequence: int = Field(ge=1)
    last_message_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def sequence_range_is_ordered(self) -> SegmentSummaryCandidate:
        if self.last_message_sequence < self.first_message_sequence:
            raise ValueError("segment summary sequence range is reversed")
        if not self.summary.strip():
            raise ValueError("segment summary must contain text")
        return self


class MemoryUpsertCandidate(ReflectionCandidateBase):
    kind: Literal["memory_upsert"] = ReflectionCandidateKind.MEMORY_UPSERT.value
    memory_kind: Literal["fact", "event", "preference", "promise", "thread", "other"]
    content: str = Field(min_length=1, max_length=4000)
    subject_kind: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=200)
    visibility: Literal["resident", "recallable", "private"] = "recallable"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    occurred_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None

    @model_validator(mode="after")
    def content_must_contain_text(self) -> MemoryUpsertCandidate:
        if not self.content.strip():
            raise ValueError("memory content must contain text")
        if (
            self.expires_at_utc is not None
            and self.occurred_at_utc is not None
            and self.expires_at_utc <= self.occurred_at_utc
        ):
            raise ValueError("memory expiry must follow occurrence time")
        return self


class ContinuityDigestCandidate(ReflectionCandidateBase):
    kind: Literal["continuity_digest"] = ReflectionCandidateKind.CONTINUITY_DIGEST.value
    content: str = Field(min_length=1, max_length=6000)
    covers_through_sequence: int = Field(ge=0)
    content_version: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def digest_content_must_contain_text(self) -> ContinuityDigestCandidate:
        if not self.content.strip():
            raise ValueError("continuity digest content must contain text")
        return self


class DiaryAppendCandidate(ReflectionCandidateBase):
    kind: Literal["diary_append"] = ReflectionCandidateKind.DIARY_APPEND.value
    game_day: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def diary_content_must_contain_text(self) -> DiaryAppendCandidate:
        if not self.content.strip():
            raise ValueError("diary content must contain text")
        return self


class CoreMemoryRewriteCandidate(ReflectionCandidateBase):
    kind: Literal["core_memory_rewrite"] = ReflectionCandidateKind.CORE_MEMORY_REWRITE.value
    content: str = Field(min_length=1, max_length=6000)
    supporting_memory_ids: tuple[str, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def core_memory_is_traceable(self) -> CoreMemoryRewriteCandidate:
        if not self.content.strip():
            raise ValueError("core memory content must contain text")
        if any(not item.strip() for item in self.supporting_memory_ids):
            raise ValueError("supporting memory IDs must be named")
        return self


class ViewRewriteCandidate(ReflectionCandidateBase):
    kind: Literal["view_rewrite"] = ReflectionCandidateKind.VIEW_REWRITE.value
    view_kind: Literal["relationship_attitude", "state_summary"]
    content: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def view_content_must_contain_text(self) -> ViewRewriteCandidate:
        if not self.content.strip():
            raise ValueError("view content must contain text")
        return self


class StateEntryCandidate(ReflectionCandidateBase):
    kind: Literal["state_entry"] = ReflectionCandidateKind.STATE_ENTRY.value
    state_kind: Literal["physical", "mood", "activity"]
    value: str = Field(min_length=1, max_length=1000)
    expires_at_utc: datetime | None = None

    @model_validator(mode="after")
    def state_value_must_contain_text(self) -> StateEntryCandidate:
        if not self.value.strip():
            raise ValueError("state entry value must contain text")
        return self


class RelationshipImpactCandidate(ReflectionCandidateBase):
    kind: Literal["relationship_impact"] = ReflectionCandidateKind.RELATIONSHIP_IMPACT.value
    dimension: Literal["affection", "trust", "attachment"] | None = None
    direction: Literal["positive", "negative", "neutral"]
    level: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def neutral_direction_requires_zero_level(self) -> RelationshipImpactCandidate:
        if self.direction == "neutral" and self.level != 0:
            raise ValueError("neutral relationship impact must have level 0")
        if self.direction != "neutral" and self.level == 0:
            raise ValueError("positive or negative relationship impact must have level 1-3")
        return self


class EntityAliasCandidate(ReflectionCandidateBase):
    kind: Literal["entity_alias"] = ReflectionCandidateKind.ENTITY_ALIAS.value
    entity_id: str = Field(min_length=1, max_length=200)
    entity_kind: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=300)
    alias_text: str = Field(min_length=1, max_length=300)


class MemoryEntityCandidate(ReflectionCandidateBase):
    kind: Literal["memory_entity"] = ReflectionCandidateKind.MEMORY_ENTITY.value
    entity_id: str = Field(min_length=1, max_length=200)
    entity_kind: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=300)


class MemoryEdgeCandidate(ReflectionCandidateBase):
    kind: Literal["memory_edge"] = ReflectionCandidateKind.MEMORY_EDGE.value
    from_entity_id: str = Field(min_length=1, max_length=200)
    to_entity_id: str = Field(min_length=1, max_length=200)
    edge_kind: str = Field(min_length=1, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_memory_id: str | None = Field(default=None, max_length=200)


ReflectionCandidate: TypeAlias = Annotated[
    SegmentSummaryCandidate
    | MemoryUpsertCandidate
    | ContinuityDigestCandidate
    | DiaryAppendCandidate
    | CoreMemoryRewriteCandidate
    | ViewRewriteCandidate
    | StateEntryCandidate
    | RelationshipImpactCandidate
    | EntityAliasCandidate
    | MemoryEntityCandidate
    | MemoryEdgeCandidate,
    Field(discriminator="kind"),
]


class ReflectionNodeActionBase(BaseModel):
    """Common, non-authoritative action metadata returned by one node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_refs: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_model_evidence_refs(value)


class SegmentSummaryAction(ReflectionNodeActionBase):
    kind: Literal["segment_summary"] = ReflectionNodeActionKind.SEGMENT_SUMMARY.value
    summary: str = Field(min_length=1, max_length=4000)
    follow_up: FollowUpDecision

    @model_validator(mode="after")
    def summary_must_contain_text(self) -> SegmentSummaryAction:
        if not self.summary.strip():
            raise ValueError("segment summary must contain text")
        return self


class RelationshipDimensionAction(BaseModel):
    """One typed relationship dimension suggested by a node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Literal["affection", "trust", "attachment"] = Field(
        description="关系维度，只能是 affection、trust 或 attachment。"
    )
    direction: Literal["positive", "negative", "neutral"] = Field(
        description="本次来源显示的关系变化方向。"
    )
    level: int = Field(
        ge=0,
        le=3,
        description="本次关系变化幅度；positive 或 negative 为 1 到 3，neutral 为 0。",
    )

    @model_validator(mode="after")
    def neutral_direction_requires_zero_level(self) -> RelationshipDimensionAction:
        if self.direction == "neutral" and self.level != 0:
            raise ValueError("neutral relationship dimension must have level 0")
        if self.direction != "neutral" and self.level == 0:
            raise ValueError("positive or negative relationship dimension must have level 1-3")
        return self


class RelationshipReflectionAction(ReflectionNodeActionBase):
    kind: Literal["relationship_reflection"] = (
        ReflectionNodeActionKind.RELATIONSHIP_REFLECTION.value
    )
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "kind": "relationship_reflection",
                    "evidence_refs": ["message:<id>"],
                    "dimensions": [
                        {
                            "dimension": "affection",
                            "direction": "positive",
                            "level": 1,
                        }
                    ],
                }
            ]
        },
    )
    dimensions: tuple[RelationshipDimensionAction, ...] = Field(
        min_length=1,
        max_length=3,
        description="本次来源显示发生变化的关系维度列表。",
    )

    @model_validator(mode="after")
    def dimensions_must_be_unique(self) -> RelationshipReflectionAction:
        dimensions = tuple(item.dimension for item in self.dimensions)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("relationship reflection dimensions must be unique")
        return self


class StateReflectionAction(ReflectionNodeActionBase):
    kind: Literal["state_reflection"] = ReflectionNodeActionKind.STATE_REFLECTION.value
    state_kind: Literal["physical", "mood", "activity"]
    value: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def state_value_must_contain_text(self) -> StateReflectionAction:
        if not self.value.strip():
            raise ValueError("state reflection value must contain text")
        return self


class ContinuityDigestAction(ReflectionNodeActionBase):
    kind: Literal["continuity_digest"] = ReflectionNodeActionKind.CONTINUITY_DIGEST.value
    content: str = Field(min_length=1, max_length=6000)
    covers_through_sequence: int = Field(ge=0)
    content_version: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def digest_content_must_contain_text(self) -> ContinuityDigestAction:
        if not self.content.strip():
            raise ValueError("continuity digest content must contain text")
        return self


class LongTermMemoryPageItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_kind: Literal["fact", "event", "preference", "promise", "thread", "other"]
    content: str = Field(min_length=1, max_length=6000)
    subject_kind: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def memory_content_must_contain_text(self) -> LongTermMemoryPageItem:
        if not self.content.strip():
            raise ValueError("long-term memory content must contain text")
        return self


class LongTermMemoryPageAction(ReflectionNodeActionBase):
    kind: Literal["long_term_memory_page"] = ReflectionNodeActionKind.LONG_TERM_MEMORY_PAGE.value
    pages: tuple[LongTermMemoryPageItem, ...] = Field(min_length=1)


class GraphEntityAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1, max_length=200)
    entity_kind: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=300)


class GraphEdgeAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_entity_id: str = Field(min_length=1, max_length=200)
    to_entity_id: str = Field(min_length=1, max_length=200)
    edge_kind: str = Field(min_length=1, max_length=100)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraphExtractionAction(ReflectionNodeActionBase):
    kind: Literal["graph_extraction"] = ReflectionNodeActionKind.GRAPH_EXTRACTION.value
    entities: tuple[GraphEntityAction, ...] = Field(default=(), max_length=64)
    edges: tuple[GraphEdgeAction, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def graph_extraction_must_contain_output(self) -> GraphExtractionAction:
        if not self.entities and not self.edges:
            raise ValueError("graph extraction must contain an entity or edge")
        return self


class DiaryAction(ReflectionNodeActionBase):
    kind: Literal["diary"] = ReflectionNodeActionKind.DIARY.value
    game_day: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def diary_content_must_contain_text(self) -> DiaryAction:
        if not self.content.strip():
            raise ValueError("diary content must contain text")
        return self


class ViewRefreshAction(ReflectionNodeActionBase):
    kind: Literal["view_refresh"] = ReflectionNodeActionKind.VIEW_REFRESH.value
    view_kind: Literal["relationship_attitude", "state_summary", "core_memory"]
    content: str = Field(min_length=1, max_length=6000)
    supporting_memory_ids: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def view_content_must_contain_text(self) -> ViewRefreshAction:
        if not self.content.strip():
            raise ValueError("view refresh content must contain text")
        return self


class NoOpReflectionAction(ReflectionNodeActionBase):
    kind: Literal["no_op"] = ReflectionNodeActionKind.NO_OP.value
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reason_must_contain_text(self) -> NoOpReflectionAction:
        if not self.reason.strip():
            raise ValueError("no-op reason must contain text")
        return self


ReflectionNodeAction: TypeAlias = Annotated[
    SegmentSummaryAction
    | RelationshipReflectionAction
    | StateReflectionAction
    | ContinuityDigestAction
    | LongTermMemoryPageAction
    | GraphExtractionAction
    | DiaryAction
    | ViewRefreshAction
    | NoOpReflectionAction,
    Field(discriminator="kind"),
]


class ReflectionBatchProposal(BaseModel):
    """Graph-level review payload built from completed node Artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["reflection_batch"] = "reflection_batch"
    outcome: ReflectionBatchOutcome = ReflectionBatchOutcome.PRODUCED
    candidates: tuple[ReflectionCandidate, ...] = Field(default=(), max_length=64)
    no_op_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def outcome_must_match_candidates(self) -> ReflectionBatchProposal:
        if self.outcome is ReflectionBatchOutcome.PRODUCED and not self.candidates:
            raise ValueError("produced reflection batch must contain candidates")
        if self.outcome is ReflectionBatchOutcome.PRODUCED and self.no_op_reason:
            raise ValueError("produced reflection batch must not contain a no-op reason")
        if self.outcome is ReflectionBatchOutcome.NO_OP:
            if self.candidates:
                raise ValueError("no-op reflection batch must not contain candidates")
            if not self.no_op_reason or not self.no_op_reason.strip():
                raise ValueError("no-op reflection batch requires a reason")
        return self


__all__ = [
    "CoreMemoryRewriteCandidate",
    "ContinuityDigestCandidate",
    "ContinuityDigestAction",
    "DiaryAppendCandidate",
    "DiaryAction",
    "EntityAliasCandidate",
    "EvidenceRef",
    "FollowUpDecision",
    "GraphEdgeAction",
    "GraphEntityAction",
    "GraphExtractionAction",
    "LongTermMemoryPageItem",
    "LongTermMemoryPageAction",
    "MemoryEdgeCandidate",
    "MemoryEntityCandidate",
    "MemoryUpsertCandidate",
    "NoOpReflectionAction",
    "ReflectionBatchOutcome",
    "ReflectionBatchProposal",
    "ReflectionCandidate",
    "ReflectionCandidateBase",
    "ReflectionCandidateKind",
    "ReflectionNodeAction",
    "ReflectionNodeActionBase",
    "ReflectionNodeActionKind",
    "RelationshipDimensionAction",
    "RelationshipReflectionAction",
    "RelationshipImpactCandidate",
    "SegmentSummaryAction",
    "SegmentSummaryCandidate",
    "StateReflectionAction",
    "StateEntryCandidate",
    "ViewRefreshAction",
    "ViewRewriteCandidate",
]
