from echo_games.contracts import RuleTransition
from echo_games.errors import GameError
from echo_games.gomoku.contracts import GOMOKU_MODELS
from echo_games.gomoku.models import (
    Color,
    GomokuConfig,
    GomokuResult,
    GomokuState,
    PlaceStoneAction,
    Stone,
    StonePlacedResult,
)


class GomokuRules:
    game_type = "gomoku"
    ruleset_id = "gomoku.freestyle"
    ruleset_version = 1
    display_name = "五子棋"
    ruleset_name = "自由规则"
    seat_ids: tuple[str, ...] = ("black", "white")
    min_players = 2
    max_players = 2
    supports_resign = True
    default_config = GomokuConfig()
    models = GOMOKU_MODELS
    instructions = "15×15 棋盘，黑方先行。轮流在空交点落子，连续五枚及以上获胜，无禁手。"

    def initialize(self, config: GomokuConfig, seat_ids: tuple[str, ...]) -> GomokuState:
        return GomokuState()

    def observe(self, state: GomokuState, seat_id: str) -> GomokuState:
        return state

    def phase(self, state: GomokuState) -> str:
        return "finished" if state.result is not None else "place_stone"

    def outcome(self, state: GomokuState) -> GomokuResult | None:
        return state.result

    def legal_actions(self, state: GomokuState, seat_id: str) -> tuple[PlaceStoneAction, ...]:
        if state.result is not None or state.current_seat_id != seat_id:
            return ()
        occupied = {(stone.x, stone.y) for stone in state.stones}
        return tuple(
            PlaceStoneAction(x=x, y=y)
            for y in range(state.size)
            for x in range(state.size)
            if (x, y) not in occupied
        )

    def apply(
        self, state: GomokuState, seat_id: str, action: PlaceStoneAction
    ) -> RuleTransition[GomokuState, StonePlacedResult, StonePlacedResult]:
        if state.result is not None:
            raise GameError("game_finished", "Game has finished")
        if state.current_seat_id != seat_id:
            raise GameError("not_current_actor", "This seat cannot act now")
        if (action.x, action.y) in {(stone.x, stone.y) for stone in state.stones}:
            raise GameError("illegal_action", "The intersection is occupied")
        stone = Stone(x=action.x, y=action.y, seat_id=seat_id)
        stones = (*state.stones, stone)
        own = {(item.x, item.y) for item in stones if item.seat_id == seat_id}
        result = None
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            count = 1
            for sign in (-1, 1):
                x, y = action.x + sign * dx, action.y + sign * dy
                while (x, y) in own:
                    count += 1
                    x, y = x + sign * dx, y + sign * dy
            if count >= 5:
                result = GomokuResult(reason="line", winner_seat_id=seat_id)
                break
        if result is None and len(stones) == state.size * state.size:
            result = GomokuResult(reason="board_full", winner_seat_id=None)
        next_seat: Color = "white" if seat_id == "black" else "black"
        placed = StonePlacedResult(x=action.x, y=action.y, seat_id=seat_id)
        return RuleTransition[GomokuState, StonePlacedResult, StonePlacedResult](
            state=GomokuState(
                stones=stones,
                current_seat_id=None if result else next_seat,
                result=result,
            ),
            result=placed,
            events=(placed,),
        )

    def resign(self, state: GomokuState, seat_id: str) -> GomokuState:
        if state.result is not None:
            raise GameError("game_finished", "Game has finished")
        if seat_id not in self.seat_ids:
            raise GameError("invalid_seat", "Unknown seat")
        result = GomokuResult(
            reason="resignation", winner_seat_id="white" if seat_id == "black" else "black"
        )
        return GomokuState(stones=state.stones, current_seat_id=None, result=result)
