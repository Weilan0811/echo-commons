from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_games.aeroplane.board import HOME_STEP, SEAT_ORDER, WAITING_STEP, SeatId
from echo_games.contracts import GameEventData

PlaneId = Annotated[int, Field(strict=True, ge=1, le=4)]
# 步数下界是机场出口的待飞位，上界是中央终点。
Step = Annotated[int, Field(strict=True, ge=WAITING_STEP, le=HOME_STEP)]
Dice = Literal[1, 2, 3, 4, 5, 6]
Phase = Literal[
    "awaiting_roll", "awaiting_action", "awaiting_chain", "awaiting_penalty", "finished"
]


class AeroplaneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RollDiceAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["roll_dice"] = "roll_dice"


class TakeOffAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["take_off"] = "take_off"
    plane_id: PlaneId


class MovePlaneAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["move_plane"] = "move_plane"
    plane_id: PlaneId


class JumpFourAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["jump_four"] = "jump_four"
    plane_id: PlaneId


class FlyShortcutAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["fly_shortcut"] = "fly_shortcut"
    plane_id: PlaneId


class EndMoveAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["end_move"] = "end_move"


class ReturnPenaltyAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["return_penalty"] = "return_penalty"
    plane_id: PlaneId


AeroplaneAction = Annotated[
    RollDiceAction
    | TakeOffAction
    | MovePlaneAction
    | JumpFourAction
    | FlyShortcutAction
    | EndMoveAction
    | ReturnPenaltyAction,
    Field(discriminator="type"),
]


class Plane(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seat_id: SeatId
    plane_id: PlaneId
    step: Step | None = None


class DiceRolled(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["dice_rolled"] = "dice_rolled"
    seat_id: SeatId
    dice: Dice


class PlaneTookOff(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["plane_took_off"] = "plane_took_off"
    seat_id: SeatId
    plane_id: PlaneId


class PlaneWalked(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["plane_walked"] = "plane_walked"
    seat_id: SeatId
    plane_id: PlaneId
    from_step: Step
    to_step: Step


class PlaneJumped(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["plane_jumped"] = "plane_jumped"
    seat_id: SeatId
    plane_id: PlaneId
    from_step: Step
    to_step: Step


class PlaneFlew(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["plane_flew"] = "plane_flew"
    seat_id: SeatId
    plane_id: PlaneId
    from_step: Step
    to_step: Step


class PlaneSentBack(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["plane_sent_back"] = "plane_sent_back"
    seat_id: SeatId
    plane_id: PlaneId
    reason: Literal["captured", "penalty"]


class MoveEnded(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["move_ended"] = "move_ended"
    seat_id: SeatId
    plane_id: PlaneId


# 动作结果与正式事件共用同一组数据类型：每个动作的主要结果本身就是一条事件。
AeroplaneActionOutcome = (
    DiceRolled | PlaneTookOff | PlaneWalked | PlaneJumped | PlaneFlew | PlaneSentBack | MoveEnded
)


class AeroplaneResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: Literal["home_complete"] = "home_complete"
    winner_seat_id: SeatId


class AeroplaneState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["aeroplane"] = "aeroplane"
    seat_order: tuple[SeatId, ...]
    planes: tuple[Plane, ...]
    current_seat_id: SeatId | None = "red"
    phase: Phase = "awaiting_roll"
    dice: Dice | None = None
    consecutive_sixes: int = Field(default=0, ge=0, le=3)
    pending_plane_id: PlaneId | None = None
    pending_arrival: Literal["step", "jump"] | None = None
    result: AeroplaneResult | None = None

    @model_validator(mode="after")
    def validate_lineup(self) -> "AeroplaneState":
        seats = self.seat_order
        if len(set(seats)) != len(seats) or any(seat not in SEAT_ORDER for seat in seats):
            raise ValueError("Seat order must list distinct known seats")
        expected = {(seat, plane) for seat in seats for plane in (1, 2, 3, 4)}
        actual = {(plane.seat_id, plane.plane_id) for plane in self.planes}
        if actual != expected:
            raise ValueError("Every seat must own exactly four planes")
        if (self.result is not None) != (self.phase == "finished"):
            raise ValueError("Only a finished game carries a result")
        if self.result is not None and self.current_seat_id is not None:
            raise ValueError("A finished game has no current actor")
        if self.phase == "awaiting_chain" and self.pending_plane_id is None:
            raise ValueError("A chain phase needs a pending plane")
        if self.phase != "awaiting_chain" and self.pending_plane_id is not None:
            raise ValueError("Only a chain phase carries a pending plane")
        return self
