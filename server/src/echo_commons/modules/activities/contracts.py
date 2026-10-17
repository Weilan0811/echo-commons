import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol

from echo_games.public import GameEventBatch, GameSummary, GameView, Participation, SeatAccess

from echo_commons.modules.perspective.contracts import ActivityObservation
from echo_commons.shared.actors import ActorRef

CharacterParticipationReason = Literal["memory_preparing", "memory_failed", "unavailable"]


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
