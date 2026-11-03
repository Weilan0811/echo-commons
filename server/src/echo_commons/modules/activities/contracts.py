import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from echo_games.public import GameEventBatch, GameSummary, GameView, Participation, SeatAccess
from pydantic import BaseModel, ConfigDict, Field

from echo_commons.modules.perspective.contracts import ActivityObservation
from echo_commons.shared.actors import ActorRef

CharacterParticipationReason = Literal["memory_preparing", "memory_failed", "unavailable"]


class ActivityContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_max_chars: int = Field(default=32000, ge=1)
    persona_direct_max_chars: int = Field(default=6000, ge=1)
    persona_projection_max_chars: int = Field(default=4000, ge=1)
    event_limit: int = Field(default=100, ge=1, le=200)


@dataclass(frozen=True)
class GameParticipantContext:
    community_id: str
    conversation_id: str
    game: GameSummary
    access: SeatAccess


class GameParticipationReader(Protocol):
    def participant_context(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
        game_id: str,
        participation_id: str | None = None,
        *,
        current: bool = True,
    ) -> GameParticipantContext: ...

    def participations(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
    ) -> tuple[Participation, ...]: ...


@dataclass(frozen=True)
class CharacterGameObservation:
    context: GameParticipantContext
    view: GameView | None
    events: GameEventBatch
    observation: ActivityObservation
