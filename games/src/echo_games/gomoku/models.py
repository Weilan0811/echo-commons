from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_games.contracts import GameEventData

Coordinate = Annotated[int, Field(strict=True, ge=0, le=14)]
Color = Literal["black", "white"]


class GomokuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlaceStoneAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["place_stone"] = "place_stone"
    x: Coordinate
    y: Coordinate


class Stone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: Coordinate
    y: Coordinate
    seat_id: Color


class GomokuResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: Literal["line", "board_full", "resignation"]
    winner_seat_id: Color | None

    @model_validator(mode="after")
    def require_winner(self) -> "GomokuResult":
        if (self.reason == "board_full") != (self.winner_seat_id is None):
            raise ValueError("Only a full-board draw has no winner")
        return self


class GomokuState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["gomoku"] = "gomoku"
    size: Literal[15] = 15
    stones: tuple[Stone, ...] = ()
    current_seat_id: Color | None = "black"
    result: GomokuResult | None = None

    @model_validator(mode="after")
    def validate_board(self) -> "GomokuState":
        if len({(stone.x, stone.y) for stone in self.stones}) != len(self.stones):
            raise ValueError("An intersection can contain only one stone")
        for index, stone in enumerate(self.stones):
            if stone.seat_id != ("black" if index % 2 == 0 else "white"):
                raise ValueError("Stones must preserve alternating move order")
        if self.result is not None:
            if self.current_seat_id is not None:
                raise ValueError("A finished board cannot have a current actor")
        elif self.current_seat_id != ("black" if len(self.stones) % 2 == 0 else "white"):
            raise ValueError("Current actor must follow the stored move order")
        return self


class StonePlacedResult(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["stone_placed"] = "stone_placed"
    x: Coordinate
    y: Coordinate
    seat_id: Color
