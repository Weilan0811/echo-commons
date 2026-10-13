from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from echo_commons.modules.memory.domain.organization import (
    CognitionOperation,
    FactOperation,
    MemoryFactContent,
    MemoryRecordRef,
)
from echo_commons.shared.actors import ActorRef


class ReflectionCandidateKind(StrEnum):
    """Typed candidate shapes carried inside one reflection batch."""

    SEGMENT_SUMMARY = "segment_summary"
    MEMORY_FACT = "memory_fact"
    MEMORY_COGNITION = "memory_cognition"
    DIARY_APPEND = "diary_append"
    CORE_MEMORY_REWRITE = "core_memory_rewrite"
    VIEW_REWRITE = "view_rewrite"
    STATE_ENTRY = "state_entry"
    RELATIONSHIP_IMPACT = "relationship_impact"
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
    MEMORY_FACT_EXTRACT = "memory_fact_extract"
    MEMORY_COGNITION_REFLECT = "memory_cognition_reflect"
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

    source_refs: tuple[str, ...] = Field(min_length=1)

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


class MemoryFactCandidate(ReflectionCandidateBase):
    kind: Literal["memory_fact"] = "memory_fact"
    operation: FactOperation


class MemoryCognitionCandidate(ReflectionCandidateBase):
    kind: Literal["memory_cognition"] = "memory_cognition"
    source_refs: tuple[str, ...] = ()
    operation: CognitionOperation

    @field_validator("source_refs")
    @classmethod
    def source_refs_must_be_named(cls, value):
        return _normalize_model_evidence_refs(value)


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
    supporting_records: tuple[MemoryRecordRef, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def core_memory_is_traceable(self) -> CoreMemoryRewriteCandidate:
        if not self.content.strip():
            raise ValueError("core memory content must contain text")
        if any(item.version < 1 for item in self.supporting_records):
            raise ValueError("supporting memory IDs must be named")
        return self


class ViewRewriteCandidate(ReflectionCandidateBase):
    kind: Literal["view_rewrite"] = ReflectionCandidateKind.VIEW_REWRITE.value
    view_kind: Literal["relationship_attitude", "state_summary"]
    content: str = Field(min_length=1, max_length=3000)
    target: ActorRef | None = None

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
    target: ActorRef
    dimension: Literal["affection", "trust", "attachment"]
    direction: Literal["positive", "negative", "neutral"]
    level: int = Field(ge=0, le=3)
    evidence_kind: Literal["interaction", "support", "conflict", "commitment"] = "interaction"

    @model_validator(mode="after")
    def neutral_direction_requires_zero_level(self) -> RelationshipImpactCandidate:
        if self.direction == "neutral" and self.level != 0:
            raise ValueError("neutral relationship impact must have level 0")
        if self.direction != "neutral" and self.level == 0:
            raise ValueError("positive or negative relationship impact must have level 1-3")
        return self


ReflectionCandidate: TypeAlias = Annotated[
    SegmentSummaryCandidate
    | MemoryFactCandidate
    | MemoryCognitionCandidate
    | ContinuityDigestCandidate
    | DiaryAppendCandidate
    | CoreMemoryRewriteCandidate
    | ViewRewriteCandidate
    | StateEntryCandidate
    | RelationshipImpactCandidate,
    Field(discriminator="kind"),
]


class ReflectionNodeActionBase(BaseModel):
    """Common, non-authoritative action metadata returned by one node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_model_evidence_refs(value)


class SegmentSummaryAction(ReflectionNodeActionBase):
    kind: Literal["segment_summary"]
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
    target: ActorRef
    evidence_kind: Literal["interaction", "support", "conflict", "commitment"] = "interaction"

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        if "evidence_kind" not in self.model_fields_set:
            result.pop("evidence_kind", None)
        return result

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
    kind: Literal["relationship_reflection"]
    dimensions: tuple[RelationshipDimensionAction, ...] = Field(
        min_length=1,
        max_length=64,
        description="本次来源显示发生变化的关系维度列表。",
    )

    @model_validator(mode="after")
    def dimensions_must_be_unique(self) -> RelationshipReflectionAction:
        dimensions = tuple((item.target, item.dimension) for item in self.dimensions)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("relationship reflection dimensions must be unique")
        return self


class StateReflectionAction(ReflectionNodeActionBase):
    kind: Literal["state_reflection"]
    state_kind: Literal["physical", "mood", "activity"]
    value: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def state_value_must_contain_text(self) -> StateReflectionAction:
        if not self.value.strip():
            raise ValueError("state reflection value must contain text")
        return self


class ContinuityDigestAction(ReflectionNodeActionBase):
    kind: Literal["continuity_digest"]
    content: str = Field(min_length=1, max_length=6000)
    covers_through_sequence: int = Field(ge=0)
    content_version: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def digest_content_must_contain_text(self) -> ContinuityDigestAction:
        if not self.content.strip():
            raise ValueError("continuity digest content must contain text")
        return self


class MemoryFactExtractAction(ReflectionNodeActionBase):
    kind: Literal["memory_fact_extract"] = "memory_fact_extract"
    facts: tuple[FactOperation, ...] = Field(min_length=1)


class SavedFactReadout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: MemoryRecordRef
    fact: MemoryFactContent


class MemoryFactReviewAction(ReflectionNodeActionBase):
    kind: Literal["memory_fact_review"] = "memory_fact_review"
    evidence_refs: tuple[str, ...] = ()
    facts: tuple[FactOperation, ...] = ()
    saved_facts: tuple[SavedFactReadout, ...] = ()
    used_candidates: int = Field(default=0, ge=0)
    used_content_chars: int = Field(default=0, ge=0)


class MemoryCognitionReflectAction(ReflectionNodeActionBase):
    kind: Literal["memory_cognition_reflect"] = "memory_cognition_reflect"
    evidence_refs: tuple[str, ...] = ()
    cognitions: tuple[CognitionOperation, ...] = Field(min_length=1)


class DiaryAction(ReflectionNodeActionBase):
    kind: Literal["diary"]
    game_day: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def diary_content_must_contain_text(self) -> DiaryAction:
        if not self.content.strip():
            raise ValueError("diary content must contain text")
        return self


class ViewRefreshAction(ReflectionNodeActionBase):
    kind: Literal["view_refresh"]
    view_kind: Literal["relationship_attitude", "state_summary", "core_memory"]
    content: str = Field(min_length=1, max_length=6000)
    supporting_records: tuple[MemoryRecordRef, ...] = Field(default=(), max_length=64)
    target: ActorRef | None = None

    @model_validator(mode="after")
    def view_content_must_contain_text(self) -> ViewRefreshAction:
        if not self.content.strip():
            raise ValueError("view refresh content must contain text")
        if self.view_kind != "core_memory" and len(self.content) > 3000:
            raise ValueError("State and relationship views must fit their 3000-character budget")
        return self


class NoOpReflectionAction(ReflectionNodeActionBase):
    kind: Literal["no_op"]
    evidence_refs: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reason_must_contain_text(self) -> NoOpReflectionAction:
        if not self.reason.strip():
            raise ValueError("no-op reason must contain text")
        return self


class ExtractedMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: str = Field(min_length=1, max_length=6000)
    sources: tuple[Annotated[int, Field(ge=1)], ...] = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def meaningful_content(cls, value):
        if not value.strip():
            raise ValueError("Memory content must contain text")
        return value


class MemoryModelAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[ExtractedMemory, ...]


class ViewModelAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: str = Field(max_length=6000)
    sources: tuple[Annotated[int, Field(ge=1)], ...] = ()


ReflectionNodeAction: TypeAlias = Annotated[
    SegmentSummaryAction
    | RelationshipReflectionAction
    | StateReflectionAction
    | ContinuityDigestAction
    | MemoryFactExtractAction
    | MemoryFactReviewAction
    | MemoryCognitionReflectAction
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
    candidates: tuple[ReflectionCandidate, ...] = ()
    no_op_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def expand_source_groups(cls, value):
        if not isinstance(value, dict) or "source_groups" not in value:
            return value
        result = dict(value)
        groups = result.pop("source_groups")
        candidates = []
        for item in result.get("candidates", ()):
            item = dict(item)
            group = item.pop("source_group")
            if not isinstance(group, int) or not 0 <= group < len(groups):
                raise ValueError("Unknown reflection source group")
            item["source_refs"] = groups[group]
            candidates.append(item)
        result["candidates"] = candidates
        return result

    def compact_dump(self) -> dict:
        result = self.model_dump(mode="json")
        groups = []
        for item in result["candidates"]:
            refs = item.pop("source_refs")
            if refs not in groups:
                groups.append(refs)
            item["source_group"] = groups.index(refs)
        result["source_groups"] = groups
        return result

    @property
    def content_chars(self) -> int:
        return sum(business_chars(item) for item in self.candidates)

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


def node_action_schema(action_kind: str, *, allow_no_op: bool) -> dict:
    short_actions = {
        "memory_fact_extract": MemoryModelAction,
        "memory_cognition_reflect": MemoryModelAction,
        "view_refresh": ViewModelAction,
    }
    action = short_actions.get(action_kind)
    if action is None:
        action = next(
            model
            for model in get_args(get_args(ReflectionNodeAction)[0])
            if get_args(model.model_fields["kind"].annotation)[0] == action_kind
        )
    if action in (MemoryModelAction, ViewModelAction):
        return action.model_json_schema()
    return TypeAdapter(action | NoOpReflectionAction if allow_no_op else action).json_schema()


def business_chars(model) -> int:
    def content(value):
        if isinstance(value, dict):
            return sum(
                len(item)
                if key in {"content", "summary", "value", "reason"} and isinstance(item, str)
                else content(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return sum(content(item) for item in value)
        return 0

    return content(model.model_dump(mode="json"))


__all__ = [
    "CoreMemoryRewriteCandidate",
    "ContinuityDigestCandidate",
    "ContinuityDigestAction",
    "DiaryAppendCandidate",
    "DiaryAction",
    "EvidenceRef",
    "FollowUpDecision",
    "MemoryFactExtractAction",
    "MemoryFactReviewAction",
    "MemoryCognitionReflectAction",
    "MemoryFactCandidate",
    "MemoryCognitionCandidate",
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
