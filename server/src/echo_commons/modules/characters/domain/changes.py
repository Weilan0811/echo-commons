from dataclasses import dataclass
from datetime import datetime

from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class RelationshipChange:
    target: ActorRef
    dimension: RelationshipDimension
    direction: RelationshipDirection
    magnitude: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class StateChange:
    kind: StateKind
    value: str
