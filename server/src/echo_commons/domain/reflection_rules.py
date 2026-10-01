"""Pure rules shared by Reflection node normalization and Runtime review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from echo_server.domain.errors import DomainInvariantError, require_non_empty, require_sequence
from echo_server.domain.relationship import RelationshipDimension


class ReflectionOutcome(StrEnum):
    """Whether a node or graph stage has material output."""

    PRODUCED = "produced"
    NO_OP = "no_op"


class RelationshipProposalDirection(StrEnum):
    """Provider-neutral direction labels used before Runtime applies scores."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class RelationshipDimensionProposal:
    """One bounded H/T/A suggestion; it does not contain a raw score."""

    dimension: RelationshipDimension | str
    direction: RelationshipProposalDirection | str
    level: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension", RelationshipDimension(self.dimension))
        object.__setattr__(self, "direction", RelationshipProposalDirection(self.direction))
        object.__setattr__(self, "level", require_sequence(self.level, "level", minimum=0))
        if self.level > 3:
            raise DomainInvariantError("relationship proposal level must be between 0 and 3")
        if self.direction is RelationshipProposalDirection.NEUTRAL and self.level != 0:
            raise DomainInvariantError("neutral relationship dimensions use level 0")
        if self.direction is not RelationshipProposalDirection.NEUTRAL and self.level == 0:
            raise DomainInvariantError("positive or negative relationship dimensions use level 1-3")


def _coerce_relationship_dimension(value: object) -> RelationshipDimensionProposal:
    if isinstance(value, RelationshipDimensionProposal):
        return value
    if isinstance(value, Mapping):
        try:
            return RelationshipDimensionProposal(
                dimension=value["dimension"],
                direction=value["direction"],
                level=value["level"],
            )
        except KeyError as exc:
            raise DomainInvariantError(f"relationship proposal is missing {exc.args[0]}") from exc
    raise DomainInvariantError("relationship dimensions must be domain proposal values or mappings")


def normalize_relationship_dimensions(
    values: Sequence[RelationshipDimensionProposal | Mapping[str, object]],
) -> tuple[RelationshipDimensionProposal, ...]:
    """Normalize and validate the three independent relationship dimensions."""

    normalized = tuple(_coerce_relationship_dimension(value) for value in values)
    if not normalized:
        raise DomainInvariantError("relationship proposal must contain at least one dimension")
    if len(normalized) > 3:
        raise DomainInvariantError(
            "relationship proposal cannot contain more than three dimensions"
        )
    dimensions = tuple(item.dimension for item in normalized)
    if len(dimensions) != len(set(dimensions)):
        raise DomainInvariantError("relationship proposal dimensions must be unique")
    return normalized


def validate_relationship_dimensions(
    values: Sequence[RelationshipDimensionProposal | Mapping[str, object]],
) -> tuple[RelationshipDimensionProposal, ...]:
    """Named validation entry point for Runtime and tests."""

    return normalize_relationship_dimensions(values)


@dataclass(frozen=True, slots=True)
class ReflectionOutcomeDecision:
    """Normalized material/no-op decision independent of any Agent schema."""

    outcome: ReflectionOutcome
    no_op_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", ReflectionOutcome(self.outcome))
        if self.outcome is ReflectionOutcome.NO_OP:
            object.__setattr__(
                self,
                "no_op_reason",
                require_non_empty(self.no_op_reason or "", "no-op reason").strip(),
            )
        elif self.no_op_reason is not None:
            raise DomainInvariantError("produced reflection output must not contain a no-op reason")


def validate_reflection_outcome(
    outcome: ReflectionOutcome | str,
    *,
    produced_items: Sequence[object] = (),
    no_op_reason: str | None = None,
) -> ReflectionOutcomeDecision:
    """Enforce explicit produced/no-op semantics for node and batch output."""

    normalized_outcome = ReflectionOutcome(outcome)
    has_items = bool(tuple(produced_items))
    if normalized_outcome is ReflectionOutcome.PRODUCED:
        if not has_items:
            raise DomainInvariantError("produced reflection output must contain items")
        if no_op_reason is not None:
            raise DomainInvariantError("produced reflection output must not contain a no-op reason")
        return ReflectionOutcomeDecision(normalized_outcome, no_op_reason=None)
    if has_items:
        raise DomainInvariantError("no-op reflection output must not contain items")
    return ReflectionOutcomeDecision(normalized_outcome, no_op_reason=no_op_reason)


def validate_no_op(reason: str | None, *, produced_items: Sequence[object] = ()) -> str:
    """Return a normalized no-op reason, rejecting hidden empty outputs."""

    decision = validate_reflection_outcome(
        ReflectionOutcome.NO_OP,
        produced_items=produced_items,
        no_op_reason=reason,
    )
    assert decision.no_op_reason is not None
    return decision.no_op_reason


def should_activate_follow_up(
    node_key: str,
    *,
    requested: bool,
    has_window_material: bool,
    target_available: bool,
    policy_allowed: bool = True,
) -> bool:
    """Apply the fixed route rules for a summary node's follow-up request."""

    normalized_node_key = require_non_empty(node_key, "node key")
    if normalized_node_key not in {"relationship_reflect", "state_reflect"}:
        raise DomainInvariantError(f"unsupported follow-up node: {normalized_node_key}")
    return bool(requested and has_window_material and target_available and policy_allowed)


__all__ = [
    "ReflectionOutcome",
    "ReflectionOutcomeDecision",
    "RelationshipDimensionProposal",
    "RelationshipProposalDirection",
    "normalize_relationship_dimensions",
    "should_activate_follow_up",
    "validate_no_op",
    "validate_reflection_outcome",
    "validate_relationship_dimensions",
]
