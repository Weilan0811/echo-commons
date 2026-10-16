from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
ConfigT = TypeVar("ConfigT", bound=BaseModel)
StateT = TypeVar("StateT", bound=BaseModel)


class GameModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GameStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class Participation(GameModel):
    participation_id: Identifier
    game_id: Identifier
    seat_id: Identifier
    participant_ref: Identifier
    invited_by_ref: Identifier
    joined_at_utc: datetime
    joined_state_version: int = Field(ge=1)
    left_at_utc: datetime | None = None
    left_state_version: int | None = Field(default=None, ge=1)
    started_state_version: int | None = Field(default=None, ge=1)


class Game(GameModel, Generic[ConfigT, StateT]):
    game_id: Identifier
    game_type: Identifier
    ruleset_id: Identifier
    ruleset_version: int = Field(ge=1)
    creator_ref: Identifier
    status: GameStatus
    state_version: int = Field(ge=1)
    config: ConfigT
    state: StateT | None = None
    created_at_utc: datetime
    updated_at_utc: datetime
    cancel_reason: str | None = None
