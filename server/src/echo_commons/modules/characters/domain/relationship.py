from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from echo_commons.modules.characters.domain.validation import (
    DomainInvariantError,
    require_non_empty,
    require_sequence,
    require_utc,
)


def _score(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainInvariantError(f"{field_name} must be a finite number from 0 to 100")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 100.0:
        raise DomainInvariantError(f"{field_name} must be a finite number from 0 to 100")
    return normalized


class RelationshipTargetKind(StrEnum):
    PLAYER = "player"
    CHARACTER = "character"


class RelationshipType(StrEnum):
    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance"
    FRIEND = "friend"


class RelationshipDimension(StrEnum):
    AFFECTION = "affection"
    TRUST = "trust"
    ATTACHMENT = "attachment"


class RelationshipDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class RelationshipEvidenceKind(StrEnum):
    """Finite Runtime-owned categories for relationship evidence."""

    INTERACTION = "interaction"
    SUPPORT = "support"
    CONFLICT = "conflict"
    COMMITMENT = "commitment"


@dataclass(frozen=True, slots=True)
class RelationshipKey:
    community_id: str
    observer_character_id: str
    target_kind: RelationshipTargetKind | str
    target_id: str

    def __post_init__(self) -> None:
        for field_name in ("community_id", "observer_character_id", "target_id"):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "target_kind", RelationshipTargetKind(self.target_kind))


@dataclass(frozen=True, slots=True)
class RelationshipValues:
    affection: float
    trust: float
    attachment: float

    def __post_init__(self) -> None:
        for dimension in RelationshipDimension:
            field_name = dimension.value
            object.__setattr__(self, field_name, _score(getattr(self, field_name), field_name))

    def get(self, dimension: RelationshipDimension | str) -> float:
        name = RelationshipDimension(dimension).value
        return getattr(self, name)

    def with_value(
        self, dimension: RelationshipDimension | str, value: float
    ) -> RelationshipValues:
        normalized = RelationshipDimension(dimension)
        return RelationshipValues(
            affection=(value if normalized is RelationshipDimension.AFFECTION else self.affection),
            trust=value if normalized is RelationshipDimension.TRUST else self.trust,
            attachment=(
                value if normalized is RelationshipDimension.ATTACHMENT else self.attachment
            ),
        )


@dataclass(frozen=True, slots=True)
class RelationshipState:
    key: RelationshipKey
    relationship_type: RelationshipType | str
    values: RelationshipValues | None
    state_version: int
    updated_at_utc: datetime
    friend_qualifying_evidence_id: UUID | None = None
    attitude_summary: str = ""
    attitude_source_refs: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.key, RelationshipKey):
            raise DomainInvariantError("key must be a RelationshipKey")
        kind = RelationshipType(self.relationship_type)
        object.__setattr__(self, "relationship_type", kind)
        if kind is RelationshipType.STRANGER:
            if self.values is not None:
                raise DomainInvariantError("strangers cannot have relationship scores")
        elif not isinstance(self.values, RelationshipValues):
            raise DomainInvariantError("acquaintances and friends need all relationship scores")
        object.__setattr__(
            self,
            "state_version",
            require_sequence(self.state_version, "state_version", minimum=0),
        )
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        if self.friend_qualifying_evidence_id is not None and not isinstance(
            self.friend_qualifying_evidence_id, UUID
        ):
            raise DomainInvariantError("friend_qualifying_evidence_id must be a UUID")
        if kind is RelationshipType.STRANGER and self.friend_qualifying_evidence_id is not None:
            raise DomainInvariantError("strangers cannot reference friend qualifying evidence")
        if kind is RelationshipType.FRIEND and self.friend_qualifying_evidence_id is None:
            raise DomainInvariantError("friend relationships require qualifying evidence")
        summary = self.attitude_summary
        if not isinstance(summary, str):
            raise DomainInvariantError("attitude_summary must be a string")
        if summary.strip():
            summary = summary.strip()
            refs = tuple(self.attitude_source_refs)
            if any(not isinstance(ref, UUID) for ref in refs):
                raise DomainInvariantError("attitude source references must be evidence UUIDs")
            if not refs:
                raise DomainInvariantError("attitude_summary needs at least one evidence source")
            if len(set(refs)) != len(refs):
                raise DomainInvariantError("attitude source references must be unique")
        else:
            summary = ""
            refs = tuple(self.attitude_source_refs)
            if refs:
                raise DomainInvariantError("attitude source references need a summary")
        if kind is RelationshipType.STRANGER and summary:
            raise DomainInvariantError("strangers cannot have a sourced relationship attitude")
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "attitude_summary", summary)
        object.__setattr__(self, "attitude_source_refs", refs)

    @classmethod
    def stranger(cls, key: RelationshipKey, *, updated_at_utc: datetime) -> RelationshipState:
        return cls(
            key=key,
            relationship_type=RelationshipType.STRANGER,
            values=None,
            state_version=0,
            updated_at_utc=updated_at_utc,
        )

    @property
    def initialized(self) -> bool:
        """Whether the relationship has values; derived from its type."""

        return self.relationship_type is not RelationshipType.STRANGER


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    """An objective, source-addressable event in one directed relationship."""

    evidence_id: UUID
    key: RelationshipKey
    evidence_kind: RelationshipEvidenceKind | str
    source_kind: str
    source_ref: str
    occurred_at_utc: datetime
    recorded_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise DomainInvariantError("evidence_id must be a UUID")
        if not isinstance(self.key, RelationshipKey):
            raise DomainInvariantError("key must be a RelationshipKey")
        object.__setattr__(self, "evidence_kind", RelationshipEvidenceKind(self.evidence_kind))
        for field_name in ("source_kind", "source_ref"):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        occurred = require_utc(self.occurred_at_utc, "occurred_at_utc")
        recorded = require_utc(self.recorded_at_utc, "recorded_at_utc")
        if recorded < occurred:
            raise DomainInvariantError("recorded_at_utc cannot precede occurred_at_utc")
        object.__setattr__(self, "occurred_at_utc", occurred)
        object.__setattr__(self, "recorded_at_utc", recorded)


@dataclass(frozen=True, slots=True)
class RelationshipImpact:
    """A discrete, evidence-linked direction; never an Agent-provided raw score."""

    evidence_id: UUID
    dimension: RelationshipDimension | str
    direction: RelationshipDirection | str
    magnitude: int

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_id, UUID):
            raise DomainInvariantError("evidence_id must be a UUID")
        object.__setattr__(self, "dimension", RelationshipDimension(self.dimension))
        direction = RelationshipDirection(self.direction)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self,
            "magnitude",
            require_sequence(self.magnitude, "magnitude", minimum=0),
        )
        if self.magnitude > 3:
            raise DomainInvariantError("magnitude must be between 0 and 3")
        if (direction is RelationshipDirection.NEUTRAL) != (self.magnitude == 0):
            raise DomainInvariantError(
                "neutral impacts use magnitude 0; directional impacts use 1-3"
            )


@dataclass(frozen=True, slots=True)
class RelationshipStepMultiplier:
    relationship_type: RelationshipType | str
    dimension: RelationshipDimension | str
    multiplier: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "relationship_type", RelationshipType(self.relationship_type))
        object.__setattr__(self, "dimension", RelationshipDimension(self.dimension))
        if isinstance(self.multiplier, bool) or not isinstance(self.multiplier, (int, float)):
            raise DomainInvariantError("multiplier must be a finite non-negative number")
        multiplier = float(self.multiplier)
        if not math.isfinite(multiplier) or multiplier < 0.0:
            raise DomainInvariantError("multiplier must be a finite non-negative number")
        object.__setattr__(self, "multiplier", multiplier)


@dataclass(frozen=True, slots=True)
class RelationshipPolicy:
    """Calibratable thresholds and event categories around fixed S5 math."""

    acquaintance_baseline: RelationshipValues
    friend_minimum_affection: float
    friend_minimum_trust: float
    initializes_on: frozenset[RelationshipEvidenceKind | str]
    friend_qualifying_kinds: frozenset[RelationshipEvidenceKind | str]
    attachment_qualifying_kinds: frozenset[RelationshipEvidenceKind | str]
    base_steps: tuple[float, float, float, float] = (0.0, 1.0, 3.0, 6.0)
    step_multipliers: tuple[RelationshipStepMultiplier, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.acquaintance_baseline, RelationshipValues):
            raise DomainInvariantError("acquaintance_baseline must be RelationshipValues")
        object.__setattr__(
            self,
            "friend_minimum_affection",
            _score(self.friend_minimum_affection, "friend_minimum_affection"),
        )
        object.__setattr__(
            self,
            "friend_minimum_trust",
            _score(self.friend_minimum_trust, "friend_minimum_trust"),
        )
        for field_name in (
            "initializes_on",
            "friend_qualifying_kinds",
            "attachment_qualifying_kinds",
        ):
            if isinstance(getattr(self, field_name), str):
                raise DomainInvariantError(f"{field_name} must be a collection of event kinds")
            values = frozenset(
                RelationshipEvidenceKind(require_non_empty(item, field_name))
                for item in getattr(self, field_name)
            )
            object.__setattr__(self, field_name, values)
        steps = tuple(float(value) for value in self.base_steps)
        if len(steps) != 4 or steps[0] != 0.0:
            raise DomainInvariantError("base_steps must define levels 0-3 and start at zero")
        if any(not math.isfinite(value) or value < 0.0 for value in steps):
            raise DomainInvariantError("base_steps must be finite non-negative numbers")
        if tuple(sorted(steps)) != steps:
            raise DomainInvariantError("base_steps must be non-decreasing")
        object.__setattr__(self, "base_steps", steps)
        multipliers = tuple(self.step_multipliers)
        if any(not isinstance(item, RelationshipStepMultiplier) for item in multipliers):
            raise DomainInvariantError("step_multipliers must contain RelationshipStepMultiplier")
        keys = [(item.relationship_type, item.dimension) for item in multipliers]
        if len(keys) != len(set(keys)):
            raise DomainInvariantError(
                "step multipliers must have unique relationship/dimension pairs"
            )
        object.__setattr__(self, "step_multipliers", multipliers)

    def step_for(
        self,
        relationship_type: RelationshipType,
        dimension: RelationshipDimension,
        magnitude: int,
    ) -> float:
        factor = next(
            (
                item.multiplier
                for item in self.step_multipliers
                if item.relationship_type is relationship_type and item.dimension is dimension
            ),
            1.0,
        )
        return self.base_steps[magnitude] * factor


@dataclass(frozen=True, slots=True)
class RelationshipAttitude:
    summary: str
    evidence_refs: tuple[UUID, ...]

    def __post_init__(self) -> None:
        summary = require_non_empty(self.summary, "summary")
        refs = tuple(self.evidence_refs)
        if any(not isinstance(ref, UUID) for ref in refs):
            raise DomainInvariantError("evidence_refs must contain evidence UUIDs")
        if not refs or len(refs) != len(set(refs)):
            raise DomainInvariantError("attitude needs unique references to supporting evidence")
        object.__setattr__(self, "summary", summary.strip())
        object.__setattr__(self, "evidence_refs", refs)


@dataclass(frozen=True, slots=True)
class AppliedRelationshipImpact:
    impact: RelationshipImpact
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass(frozen=True, slots=True)
class RelationshipTransition:
    state: RelationshipState
    applied_impacts: tuple[AppliedRelationshipImpact, ...]
    initialized_now: bool
    promoted_to_friend: bool
    state_changed: bool

    @property
    def changed(self) -> bool:
        return self.state_changed


def apply_relationship_evidence(
    state: RelationshipState,
    evidence: RelationshipEvidence,
    impacts: tuple[RelationshipImpact, ...] | list[RelationshipImpact],
    policy: RelationshipPolicy,
    *,
    expected_version: int,
    updated_at_utc: datetime,
    attitude: RelationshipAttitude | None = None,
) -> RelationshipTransition:
    """Apply one reviewed, source-linked event with deterministic bounded steps."""

    version = require_sequence(expected_version, "expected_version", minimum=0)
    if version != state.state_version:
        raise DomainInvariantError(
            f"relationship state version conflict: expected {version}, found {state.state_version}"
        )
    if evidence.key != state.key:
        raise DomainInvariantError("relationship evidence belongs to a different directed relation")
    updated = require_utc(updated_at_utc, "updated_at_utc")
    if updated < evidence.recorded_at_utc:
        raise DomainInvariantError(
            "relationship state cannot update before its evidence is recorded"
        )
    if updated < state.updated_at_utc:
        raise DomainInvariantError("relationship state time cannot move backwards")
    if any(item.evidence_id != evidence.evidence_id for item in impacts):
        raise DomainInvariantError("relationship impacts must reference the current evidence")
    dimensions = [item.dimension for item in impacts]
    if len(dimensions) != len(set(dimensions)):
        raise DomainInvariantError(
            "an evidence event can impact each relationship dimension at most once"
        )

    initialized_now = False
    relation_type = state.relationship_type
    values = state.values
    if not state.initialized:
        if evidence.evidence_kind not in policy.initializes_on:
            if impacts or attitude is not None:
                raise DomainInvariantError(
                    "stranger relationships cannot accept scores or attitude changes"
                )
            return RelationshipTransition(
                state=state,
                applied_impacts=(),
                initialized_now=False,
                promoted_to_friend=False,
                state_changed=False,
            )
        relation_type = RelationshipType.ACQUAINTANCE
        values = policy.acquaintance_baseline
        initialized_now = True

    if values is None:
        raise DomainInvariantError("initialized relationships require relationship scores")

    friend_evidence_id = state.friend_qualifying_evidence_id
    if friend_evidence_id is None and evidence.evidence_kind in policy.friend_qualifying_kinds:
        friend_evidence_id = evidence.evidence_id
    applied: list[AppliedRelationshipImpact] = []
    for impact in impacts:
        before = values.get(impact.dimension)
        step = policy.step_for(relation_type, impact.dimension, impact.magnitude)
        if (
            impact.dimension is RelationshipDimension.ATTACHMENT
            and evidence.evidence_kind not in policy.attachment_qualifying_kinds
        ):
            step = 0.0
        if impact.direction is RelationshipDirection.UP:
            delta = step * (100.0 - before) / 100.0
            after = min(100.0, before + delta)
        elif impact.direction is RelationshipDirection.DOWN:
            delta = step * before / 100.0
            after = max(0.0, before - delta)
        else:
            after = before
        values = values.with_value(impact.dimension, after)
        applied.append(AppliedRelationshipImpact(impact=impact, before=before, after=after))

    if attitude is not None:
        attitude_summary = attitude.summary
        attitude_refs = attitude.evidence_refs
    else:
        attitude_summary = state.attitude_summary
        attitude_refs = state.attitude_source_refs

    promoted_to_friend = (
        relation_type is RelationshipType.ACQUAINTANCE
        and friend_evidence_id is not None
        and values.affection >= policy.friend_minimum_affection
        and values.trust >= policy.friend_minimum_trust
    )
    if promoted_to_friend:
        relation_type = RelationshipType.FRIEND

    changed = (
        initialized_now
        or relation_type is not state.relationship_type
        or friend_evidence_id != state.friend_qualifying_evidence_id
        or values != state.values
        or attitude_summary != state.attitude_summary
        or attitude_refs != state.attitude_source_refs
    )
    next_state = RelationshipState(
        key=state.key,
        relationship_type=relation_type,
        values=values,
        state_version=state.state_version + 1 if changed else state.state_version,
        updated_at_utc=updated if changed else state.updated_at_utc,
        friend_qualifying_evidence_id=friend_evidence_id,
        attitude_summary=attitude_summary,
        attitude_source_refs=attitude_refs,
    )
    return RelationshipTransition(
        state=next_state,
        applied_impacts=tuple(applied),
        initialized_now=initialized_now,
        promoted_to_friend=promoted_to_friend,
        state_changed=changed,
    )


__all__ = [
    "AppliedRelationshipImpact",
    "RelationshipAttitude",
    "RelationshipDimension",
    "RelationshipDirection",
    "RelationshipEvidence",
    "RelationshipEvidenceKind",
    "RelationshipImpact",
    "RelationshipKey",
    "RelationshipPolicy",
    "RelationshipState",
    "RelationshipStepMultiplier",
    "RelationshipTargetKind",
    "RelationshipTransition",
    "RelationshipType",
    "RelationshipValues",
    "apply_relationship_evidence",
]
