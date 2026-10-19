from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_games.contracts import GameEventData
from echo_games.kingdomino.tiles import Terrain

SeatId = Literal["pink", "yellow", "green", "blue"]
SEAT_ORDER: tuple[SeatId, ...] = ("pink", "yellow", "green", "blue")
# 起始地块固定在原点 (0,0)，5×5 外接矩形约束使任一已占格的坐标落在 [-4,4]。
CellCoordinate = Annotated[int, Field(strict=True, ge=-4, le=4)]
DominoId = Annotated[int, Field(strict=True, ge=1, le=48)]
Crowns = Annotated[int, Field(strict=True, ge=0, le=3)]
Direction = Literal["right", "down", "left", "up"]
Phase = Literal["seeding", "placing", "choosing", "finished"]

# 起始地块地形参与领域计分，同时对连接视为万能地块（《Kingdomino 基础规则》第 6、7 节）。
START_TERRAIN: Terrain = "field"
DIRECTIONS: tuple[Direction, ...] = ("right", "down", "left", "up")
OFFSETS: dict[Direction, tuple[int, int]] = {
    "right": (1, 0),
    "left": (-1, 0),
    "up": (0, 1),
    "down": (0, -1),
}
NEIGHBORS: tuple[tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


class KingdominoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlaceInitialKingAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["place_initial_king"] = "place_initial_king"
    domino_id: DominoId


class PlaceDominoAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["place_domino"] = "place_domino"
    cell_x: CellCoordinate
    cell_y: CellCoordinate
    direction: Direction


class ChooseDominoAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["choose_domino"] = "choose_domino"
    domino_id: DominoId


class DiscardDominoAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["discard_domino"] = "discard_domino"


KingdominoAction = Annotated[
    PlaceInitialKingAction | PlaceDominoAction | ChooseDominoAction | DiscardDominoAction,
    Field(discriminator="type"),
]


class Cell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: CellCoordinate
    y: CellCoordinate
    terrain: Terrain
    crowns: Crowns = 0
    start: bool = False


class Kingdom(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seat_id: SeatId
    cells: tuple[Cell, ...]

    @model_validator(mode="after")
    def require_start_cell(self) -> "Kingdom":
        if len({(cell.x, cell.y) for cell in self.cells}) != len(self.cells):
            raise ValueError("A cell position can hold at most one cell")
        if sum(1 for cell in self.cells if cell.start) != 1:
            raise ValueError("A kingdom carries exactly one start cell")
        return self


class LineSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    domino_id: DominoId
    king_seat_id: SeatId | None = None


class InitialKingPlaced(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["initial_king_placed"] = "initial_king_placed"
    seat_id: SeatId
    domino_id: DominoId


class DominoPlaced(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["domino_placed"] = "domino_placed"
    seat_id: SeatId
    domino_id: DominoId
    cells: tuple[Cell, ...]


class DominoDiscarded(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["domino_discarded"] = "domino_discarded"
    seat_id: SeatId
    domino_id: DominoId


class DominoChosen(GameEventData):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["domino_chosen"] = "domino_chosen"
    seat_id: SeatId
    domino_id: DominoId


# 动作结果与正式事件共用同一组数据类型：每个动作的主要结果本身就是一条事件。
KingdominoActionOutcome = InitialKingPlaced | DominoPlaced | DominoDiscarded | DominoChosen


class SeatScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seat_id: SeatId
    total: int = Field(ge=0)
    largest_domain: int = Field(ge=0)
    crowns: int = Field(ge=0)


class KingdominoResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: Literal["scored"] = "scored"
    winner_seat_ids: tuple[SeatId, ...]
    scores: tuple[SeatScore, ...]


class KingdominoBoard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seat_order: tuple[SeatId, ...]
    kings_per_seat: Literal[1, 2]
    deck_remaining: int = Field(ge=0)
    line: tuple[LineSlot, ...]
    next_line: tuple[LineSlot, ...]
    kingdoms: tuple[Kingdom, ...]
    discarded: tuple[DominoId, ...]
    phase: Phase
    current_seat_id: SeatId | None
    active_domino_id: DominoId | None
    seeding_remaining: int = Field(ge=0)


class KingdominoState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["kingdomino"] = "kingdomino"
    seat_order: tuple[SeatId, ...]
    kings_per_seat: Literal[1, 2]
    deck: tuple[DominoId, ...]
    line: tuple[LineSlot, ...]
    next_line: tuple[LineSlot, ...]
    kingdoms: tuple[Kingdom, ...]
    discarded: tuple[DominoId, ...] = ()
    seeding_queue: tuple[SeatId, ...]
    seeds_drawn: int = Field(default=0, ge=0)
    active_index: int = Field(default=0, ge=0)
    phase: Phase = "seeding"
    result: KingdominoResult | None = None

    @model_validator(mode="after")
    def validate_setup(self) -> "KingdominoState":
        seats = self.seat_order
        if len(set(seats)) != len(seats) or any(seat not in SEAT_ORDER for seat in seats):
            raise ValueError("Seat order must list distinct known seats")
        if len(self.kingdoms) != len(seats) or {k.seat_id for k in self.kingdoms} != set(seats):
            raise ValueError("Kingdoms must match the seat order")
        expected = len(seats) * self.kings_per_seat
        if len(self.line) != expected or len(self.next_line) not in (0, expected):
            raise ValueError("Lines must hold the declared number of kings")
        if len(self.seeding_queue) not in (0, expected):
            raise ValueError("The king draw order must hold the declared number of kings")
        line_ids = [slot.domino_id for slot in self.line]
        next_ids = [slot.domino_id for slot in self.next_line]
        if line_ids != sorted(line_ids) or len(set(line_ids)) != len(line_ids):
            raise ValueError("The king line is ordered by domino and repeats none")
        if next_ids != sorted(next_ids) or len(set(next_ids)) != len(next_ids):
            raise ValueError("The new line is ordered by domino and repeats none")
        pool = [*line_ids, *next_ids, *self.deck]
        if len(set(pool)) != len(pool):
            raise ValueError("A domino is used at most once")
        # 本回合弃置的地块仍留在国王线上供轮序定位，故只要求它不复用于牌堆与新线。
        if len(set(self.discarded)) != len(self.discarded):
            raise ValueError("A domino is discarded at most once")
        if set(self.discarded) & (set(next_ids) | set(self.deck)):
            raise ValueError("A discarded domino cannot return to play")
        if self.phase == "seeding":
            if self.result is not None or not self.seeding_queue:
                raise ValueError("Seeding needs an unfinished draw order")
            if self.seeds_drawn >= len(self.seeding_queue):
                raise ValueError("Seeding must have a king left to draw")
        elif self.seeding_queue:
            raise ValueError("Only seeding keeps a king draw order")
        if self.phase in ("placing", "choosing"):
            if any(slot.king_seat_id is None for slot in self.line):
                raise ValueError("Every king must be seated before acting")
            if self.phase == "choosing" and not self.next_line:
                raise ValueError("Choosing needs a new line")
        if (self.result is not None) != (self.phase == "finished"):
            raise ValueError("Only a finished game carries a result")
        return self
