import random
from typing import Literal, cast

from echo_games.contracts import RuleTransition
from echo_games.errors import GameError
from echo_games.kingdomino.contracts import KINGDOMINO_MODELS
from echo_games.kingdomino.models import (
    DIRECTIONS,
    NEIGHBORS,
    OFFSETS,
    SEAT_ORDER,
    START_TERRAIN,
    Cell,
    ChooseDominoAction,
    Direction,
    DiscardDominoAction,
    DominoChosen,
    DominoDiscarded,
    DominoPlaced,
    InitialKingPlaced,
    Kingdom,
    KingdominoAction,
    KingdominoActionOutcome,
    KingdominoBoard,
    KingdominoConfig,
    KingdominoResult,
    KingdominoState,
    LineSlot,
    PlaceDominoAction,
    PlaceInitialKingAction,
    SeatId,
)
from echo_games.kingdomino.scoring import score_kingdoms
from echo_games.kingdomino.tiles import TILE_IDS, TILES_BY_ID, Tile, TileHalf

# 人数决定使用地块数量与每席国王数（《Kingdomino 基础规则》第 4 节）。
DECK_SIZE: dict[int, int] = {2: 24, 3: 36, 4: 48}
KINGS_PER_SEAT: dict[int, int] = {2: 2, 3: 1, 4: 1}
BOARD_SIZE = 5
COORDINATE_RANGE = range(-4, 5)


class KingdominoRules:
    game_type = "kingdomino"
    ruleset_id = "kingdomino.classic"
    ruleset_version = 1
    display_name = "Kingdomino"
    ruleset_name = "经典规则"
    seat_ids: tuple[str, ...] = SEAT_ORDER
    min_players = 2
    max_players = 4
    supports_resign = False
    default_config = KingdominoConfig()
    models = KINGDOMINO_MODELS
    instructions = (
        "拼放 5×5 王国。按国王线编号升序行动：先把自己国王所在的地块按连接规则放入王国，"
        "再到新线选一张地块放上国王；相邻格地形需一致（起始地块除外），无法放置时弃置。"
        "最终按各地形领域「格数 × 皇冠数」之和计分，分高者胜。"
    )

    def __init__(self, random_source: random.Random | None = None) -> None:
        # 洗牌、排除与首轮国王抽取顺序都由玩法持有的随机源产生并写入状态，接口无需改动。
        self._random = random_source if random_source is not None else random.Random()

    def initialize(self, config: KingdominoConfig, seat_ids: tuple[str, ...]) -> KingdominoState:
        seats = tuple(cast(SeatId, seat_id) for seat_id in seat_ids)
        count = len(seats)
        deck_size = DECK_SIZE[count]
        kings_per_seat = cast(Literal[1, 2], KINGS_PER_SEAT[count])
        line_size = count * kings_per_seat
        shuffled = self._shuffled()
        deck = tuple(shuffled[:deck_size])
        line = tuple(LineSlot(domino_id=value) for value in sorted(deck[:line_size]))
        next_line = tuple(
            LineSlot(domino_id=value) for value in sorted(deck[line_size : line_size * 2])
        )
        draw_order = [seat for seat in seats for _ in range(kings_per_seat)]
        self._random.shuffle(draw_order)
        return KingdominoState(
            seat_order=seats,
            kings_per_seat=kings_per_seat,
            deck=deck[line_size * 2 :],
            line=line,
            next_line=next_line,
            kingdoms=tuple(self._new_kingdom(seat) for seat in seats),
            seeding_queue=tuple(draw_order),
        )

    def observe(self, state: KingdominoState, seat_id: str) -> KingdominoBoard:
        # 牌堆内容隐藏，只公开剩余数量；国王线、新线与各家王国都是公开信息。
        return KingdominoBoard(
            seat_order=state.seat_order,
            kings_per_seat=state.kings_per_seat,
            deck_remaining=len(state.deck),
            line=state.line,
            next_line=state.next_line,
            kingdoms=state.kingdoms,
            discarded=state.discarded,
            phase=state.phase,
            current_seat_id=self._current_seat(state),
            active_domino_id=(
                state.line[state.active_index].domino_id
                if state.phase in ("placing", "choosing")
                else None
            ),
            seeding_remaining=(
                len(state.seeding_queue) - state.seeds_drawn if state.phase == "seeding" else 0
            ),
        )

    def phase(self, state: KingdominoState) -> str:
        return state.phase

    def outcome(self, state: KingdominoState) -> KingdominoResult | None:
        return state.result

    def legal_actions(self, state: KingdominoState, seat_id: str) -> tuple[KingdominoAction, ...]:
        if state.phase == "finished" or self._current_seat(state) != seat_id:
            return ()
        if state.phase == "seeding":
            return tuple(
                PlaceInitialKingAction(domino_id=slot.domino_id)
                for slot in state.line
                if slot.king_seat_id is None
            )
        if state.phase == "placing":
            domino_id = state.line[state.active_index].domino_id
            placements = self._placements(self._kingdom(state, cast(SeatId, seat_id)), domino_id)
            return placements if placements else (DiscardDominoAction(),)
        if state.phase == "choosing":
            return tuple(
                ChooseDominoAction(domino_id=slot.domino_id)
                for slot in state.next_line
                if slot.king_seat_id is None
            )
        return ()

    def apply(
        self, state: KingdominoState, seat_id: str, action: KingdominoAction
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        if state.phase == "finished":
            raise GameError("game_finished", "Game has finished")
        if self._current_seat(state) != seat_id:
            raise GameError("not_current_actor", "This seat cannot act now")
        if state.phase == "seeding":
            return self._seed(state, seat_id, action)
        if state.phase == "placing":
            return self._place(state, seat_id, action)
        if state.phase == "choosing":
            return self._choose(state, seat_id, action)
        raise GameError("illegal_action", "Unknown phase")

    def resign(self, state: KingdominoState, seat_id: str) -> KingdominoState:
        # 基础版本不开放进行中退出，与 supports_resign=False 一致。
        raise GameError("operation_not_supported", "Kingdomino does not support resigning")

    # 以下为规则内部实现，动作判别联合与回合推进都集中在 apply。

    def _shuffled(self) -> list[int]:
        tiles = list(TILE_IDS)
        self._random.shuffle(tiles)
        return tiles

    def _new_kingdom(self, seat: SeatId) -> Kingdom:
        start = Cell(x=0, y=0, terrain=START_TERRAIN, start=True)
        return Kingdom(seat_id=seat, cells=(start,))

    def _current_seat(self, state: KingdominoState) -> SeatId | None:
        if state.phase == "finished":
            return None
        if state.phase == "seeding":
            return state.seeding_queue[state.seeds_drawn]
        return state.line[state.active_index].king_seat_id

    def _kingdom(self, state: KingdominoState, seat: SeatId) -> Kingdom:
        for kingdom in state.kingdoms:
            if kingdom.seat_id == seat:
                return kingdom
        raise GameError("invalid_seat", "Unknown seat")

    def _connects(
        self, kingdom: Kingdom, halves: tuple[tuple[tuple[int, int], TileHalf], ...]
    ) -> bool:
        # 相接条件：触到起始地块即成立；否则相接的两格至少有一对地形相同（第 6 节）。
        existing = {(cell.x, cell.y): cell for cell in kingdom.cells}
        for (x, y), half in halves:
            for dx, dy in NEIGHBORS:
                neighbor = existing.get((x + dx, y + dy))
                if neighbor is None:
                    continue
                if neighbor.start or neighbor.terrain == half.terrain:
                    return True
        return False

    def _placement_cells(
        self, kingdom: Kingdom, tile: Tile, cell_x: int, cell_y: int, direction: Direction
    ) -> tuple[Cell, ...] | None:
        dx, dy = OFFSETS[direction]
        a = (cell_x, cell_y)
        b = (cell_x + dx, cell_y + dy)
        occupied = {(cell.x, cell.y) for cell in kingdom.cells}
        if a in occupied or b in occupied:
            return None
        xs = [cell.x for cell in kingdom.cells] + [a[0], b[0]]
        ys = [cell.y for cell in kingdom.cells] + [a[1], b[1]]
        if max(xs) - min(xs) + 1 > BOARD_SIZE or max(ys) - min(ys) + 1 > BOARD_SIZE:
            return None
        if not self._connects(kingdom, ((a, tile.a), (b, tile.b))):
            return None
        return (
            Cell(x=a[0], y=a[1], terrain=tile.a.terrain, crowns=tile.a.crowns),
            Cell(x=b[0], y=b[1], terrain=tile.b.terrain, crowns=tile.b.crowns),
        )

    def _placements(self, kingdom: Kingdom, domino_id: int) -> tuple[PlaceDominoAction, ...]:
        tile = TILES_BY_ID[domino_id]
        return tuple(
            PlaceDominoAction(cell_x=x, cell_y=y, direction=direction)
            for x in COORDINATE_RANGE
            for y in COORDINATE_RANGE
            for direction in DIRECTIONS
            if self._placement_cells(kingdom, tile, x, y, direction) is not None
        )

    def _transition(
        self, state: KingdominoState, events: list[KingdominoActionOutcome]
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        return RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome](
            state=state, result=events[0], events=tuple(events)
        )

    def _seed(
        self, state: KingdominoState, seat_id: str, action: KingdominoAction
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        if not isinstance(action, PlaceInitialKingAction):
            raise GameError("illegal_action", "The first round only places kings")
        seat = cast(SeatId, seat_id)
        if not any(
            slot.domino_id == action.domino_id and slot.king_seat_id is None for slot in state.line
        ):
            raise GameError("illegal_action", "That domino cannot take a king")
        line = tuple(
            slot.model_copy(update={"king_seat_id": seat})
            if slot.domino_id == action.domino_id
            else slot
            for slot in state.line
        )
        events: list[KingdominoActionOutcome] = [
            InitialKingPlaced(seat_id=seat, domino_id=action.domino_id)
        ]
        drawn = state.seeds_drawn + 1
        if drawn < len(state.seeding_queue):
            return self._transition(
                state.model_copy(update={"line": line, "seeds_drawn": drawn}), events
            )
        return self._transition(
            state.model_copy(
                update={
                    "line": line,
                    "seeding_queue": (),
                    "seeds_drawn": 0,
                    "active_index": 0,
                    "phase": "placing",
                }
            ),
            events,
        )

    def _place(
        self, state: KingdominoState, seat_id: str, action: KingdominoAction
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        seat = cast(SeatId, seat_id)
        slot = state.line[state.active_index]
        kingdom = self._kingdom(state, seat)
        if isinstance(action, PlaceDominoAction):
            cells = self._placement_cells(
                kingdom, TILES_BY_ID[slot.domino_id], action.cell_x, action.cell_y, action.direction
            )
            if cells is None:
                raise GameError("illegal_action", "The domino cannot be placed there")
            kingdoms = tuple(
                item.model_copy(update={"cells": (*item.cells, *cells)})
                if item.seat_id == seat
                else item
                for item in state.kingdoms
            )
            events: list[KingdominoActionOutcome] = [
                DominoPlaced(seat_id=seat, domino_id=slot.domino_id, cells=cells)
            ]
            return self._accepted(state.model_copy(update={"kingdoms": kingdoms}), events)
        if not isinstance(action, DiscardDominoAction):
            raise GameError("illegal_action", "This phase places the current domino")
        if self._placements(kingdom, slot.domino_id):
            raise GameError("illegal_action", "The domino can still be placed")
        events = [DominoDiscarded(seat_id=seat, domino_id=slot.domino_id)]
        return self._accepted(
            state.model_copy(update={"discarded": (*state.discarded, slot.domino_id)}), events
        )

    def _accepted(
        self, state: KingdominoState, events: list[KingdominoActionOutcome]
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        # 放置或弃置完成：有新线则同一持有者进入选块，否则推进国王线。
        if state.next_line:
            return self._transition(state.model_copy(update={"phase": "choosing"}), events)
        return self._advance_line(state, events)

    def _choose(
        self, state: KingdominoState, seat_id: str, action: KingdominoAction
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        if not isinstance(action, ChooseDominoAction):
            raise GameError("illegal_action", "This phase places a king on the new line")
        seat = cast(SeatId, seat_id)
        if not any(
            slot.domino_id == action.domino_id and slot.king_seat_id is None
            for slot in state.next_line
        ):
            raise GameError("illegal_action", "That domino cannot take a king")
        next_line = tuple(
            slot.model_copy(update={"king_seat_id": seat})
            if slot.domino_id == action.domino_id
            else slot
            for slot in state.next_line
        )
        events: list[KingdominoActionOutcome] = [
            DominoChosen(seat_id=seat, domino_id=action.domino_id)
        ]
        return self._advance_line(state.model_copy(update={"next_line": next_line}), events)

    def _advance_line(
        self, state: KingdominoState, events: list[KingdominoActionOutcome]
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        index = state.active_index + 1
        if index < len(state.line):
            return self._transition(
                state.model_copy(update={"phase": "placing", "active_index": index}), events
            )
        return self._end_round(state, events)

    def _end_round(
        self, state: KingdominoState, events: list[KingdominoActionOutcome]
    ) -> RuleTransition[KingdominoState, KingdominoActionOutcome, KingdominoActionOutcome]:
        if not state.next_line:
            # 没有新线说明牌堆已空、本回合是最后一回合，放置结束后直接结算。
            result = score_kingdoms(state.kingdoms)
            return self._transition(
                state.model_copy(
                    update={
                        "phase": "finished",
                        "active_index": len(state.line),
                        "result": result,
                    }
                ),
                events,
            )
        size = len(state.next_line)
        if len(state.deck) >= size:
            drawn = tuple(LineSlot(domino_id=value) for value in sorted(state.deck[:size]))
            deck = state.deck[size:]
        else:
            drawn = ()
            deck = state.deck
        return self._transition(
            state.model_copy(
                update={
                    "line": state.next_line,
                    "next_line": drawn,
                    "deck": deck,
                    "active_index": 0,
                    "phase": "placing",
                }
            ),
            events,
        )
