import random
from typing import cast

from echo_games.aeroplane import board
from echo_games.aeroplane.board import SeatId
from echo_games.aeroplane.contracts import AEROPLANE_MODELS
from echo_games.aeroplane.models import (
    AeroplaneAction,
    AeroplaneActionOutcome,
    AeroplaneConfig,
    AeroplaneResult,
    AeroplaneState,
    Dice,
    DiceRolled,
    EndMoveAction,
    FlyShortcutAction,
    JumpFourAction,
    MoveEnded,
    MovePlaneAction,
    Plane,
    PlaneFlew,
    PlaneJumped,
    PlaneSentBack,
    PlaneTookOff,
    PlaneWalked,
    ReturnPenaltyAction,
    RollDiceAction,
    TakeOffAction,
)
from echo_games.contracts import RuleTransition
from echo_games.errors import GameError


class AeroplaneRules:
    game_type = "aeroplane"
    ruleset_id = "aeroplane.traditional"
    ruleset_version = 1
    display_name = "飞行棋"
    ruleset_name = "传统玩法"
    seat_ids: tuple[str, ...] = board.SEAT_ORDER
    min_players = 2
    max_players = 4
    default_config = AeroplaneConfig()
    models = AEROPLANE_MODELS
    instructions = (
        "四色跑道与机场。掷到 6 可起飞或前进 6 格，并追加掷骰；踏上本色格可跳四格，"
        "踏上本色虚线格可沿虚线飞越；被追上的棋子返回机场；"
        "同一回合连续三次 6 由玩家选一枚棋子返航。"
    )

    def __init__(self, random_source: random.Random | None = None) -> None:
        # 随机源由玩法持有并注入，掷骰结果写入状态，重启后从状态恢复，接口无需改动。
        self._random = random_source if random_source is not None else random.Random()

    def initialize(self, config: AeroplaneConfig, seat_ids: tuple[str, ...]) -> AeroplaneState:
        seats = tuple(cast(SeatId, seat_id) for seat_id in seat_ids)
        planes = tuple(
            Plane(seat_id=seat, plane_id=index) for seat in seats for index in (1, 2, 3, 4)
        )
        return AeroplaneState(seat_order=seats, planes=planes, current_seat_id=seats[0])

    def observe(self, state: AeroplaneState, seat_id: str) -> AeroplaneState:
        # 飞行棋没有隐藏信息，四席观察内容相同。
        return state

    def phase(self, state: AeroplaneState) -> str:
        return state.phase

    def outcome(self, state: AeroplaneState) -> AeroplaneResult | None:
        return state.result

    def legal_actions(self, state: AeroplaneState, seat_id: str) -> tuple[AeroplaneAction, ...]:
        if state.result is not None or state.current_seat_id != seat_id:
            return ()
        if state.phase == "awaiting_roll":
            return (RollDiceAction(),)
        if state.phase == "awaiting_action" and state.dice is not None:
            return self._action_choices(state, seat_id, state.dice)
        if state.phase == "awaiting_chain":
            return self._chain_choices(state, seat_id)
        if state.phase == "awaiting_penalty":
            return tuple(
                ReturnPenaltyAction(plane_id=plane.plane_id)
                for plane in self._board_planes(state, seat_id)
            )
        return ()

    def apply(
        self, state: AeroplaneState, seat_id: str, action: AeroplaneAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.result is not None:
            raise GameError("game_finished", "Game has finished")
        if state.current_seat_id != seat_id:
            raise GameError("not_current_actor", "This seat cannot act now")
        if isinstance(action, RollDiceAction):
            return self._roll(state, seat_id)
        if isinstance(action, TakeOffAction):
            return self._take_off(state, seat_id, action)
        if isinstance(action, MovePlaneAction):
            return self._move(state, seat_id, action)
        if isinstance(action, JumpFourAction):
            return self._jump(state, seat_id, action)
        if isinstance(action, FlyShortcutAction):
            return self._fly(state, seat_id, action)
        if isinstance(action, EndMoveAction):
            return self._end_move(state, seat_id)
        if isinstance(action, ReturnPenaltyAction):
            return self._penalty(state, seat_id, action)
        raise GameError("illegal_action", "Unknown action")

    def resign(self, state: AeroplaneState, seat_id: str) -> AeroplaneState:
        # 基础飞行棋不开放进行中个人退出，认输由生命周期契约返回不支持。
        raise GameError("operation_not_supported", "Aeroplane does not support resigning")

    # 以下为规则内部实现，动作判别联合与阶段推进都集中在 apply。

    def _base_planes(self, state: AeroplaneState, seat_id: str) -> tuple[Plane, ...]:
        return tuple(
            plane for plane in state.planes if plane.seat_id == seat_id and plane.step is None
        )

    def _board_planes(self, state: AeroplaneState, seat_id: str) -> tuple[Plane, ...]:
        return tuple(
            plane
            for plane in state.planes
            if plane.seat_id == seat_id
            and plane.step is not None
            and plane.step < board.HOME_STEP
        )

    def _find_plane(self, state: AeroplaneState, seat_id: str, plane_id: int | None) -> Plane:
        for plane in state.planes:
            if plane.seat_id == seat_id and plane.plane_id == plane_id:
                return plane
        raise GameError("illegal_action", "The plane does not belong to this seat")

    def _set_plane(
        self, planes: tuple[Plane, ...], seat_id: str, plane_id: int, step: int | None
    ) -> tuple[Plane, ...]:
        return tuple(
            plane.model_copy(update={"step": step})
            if plane.seat_id == seat_id and plane.plane_id == plane_id
            else plane
            for plane in planes
        )

    def _capture(
        self, planes: tuple[Plane, ...], acting_seat: str, cell: int
    ) -> tuple[tuple[Plane, ...], list[AeroplaneActionOutcome]]:
        updated: list[Plane] = []
        events: list[AeroplaneActionOutcome] = []
        for plane in planes:
            if (
                plane.seat_id != acting_seat
                and plane.step is not None
                and plane.step <= board.LAST_RING_STEP
                and board.ring_cell(plane.seat_id, plane.step) == cell
            ):
                updated.append(plane.model_copy(update={"step": None}))
                events.append(
                    PlaneSentBack(seat_id=plane.seat_id, plane_id=plane.plane_id, reason="captured")
                )
            else:
                updated.append(plane)
        return tuple(updated), events

    def _crossing_capture(
        self, planes: tuple[Plane, ...], acting_seat: str
    ) -> tuple[tuple[Plane, ...], list[AeroplaneActionOutcome]]:
        diagonal = board.DIAGONAL_SEAT[cast(SeatId, acting_seat)]
        updated: list[Plane] = []
        events: list[AeroplaneActionOutcome] = []
        for plane in planes:
            if plane.seat_id == diagonal and plane.step == board.CROSSING_STEP:
                updated.append(plane.model_copy(update={"step": None}))
                events.append(
                    PlaneSentBack(seat_id=plane.seat_id, plane_id=plane.plane_id, reason="crossing")
                )
            else:
                updated.append(plane)
        return tuple(updated), events

    def _action_choices(
        self, state: AeroplaneState, seat_id: str, dice: int
    ) -> tuple[AeroplaneAction, ...]:
        choices: list[AeroplaneAction] = []
        if dice == 6:
            choices.extend(
                TakeOffAction(plane_id=plane.plane_id)
                for plane in self._base_planes(state, seat_id)
            )
        choices.extend(
            MovePlaneAction(plane_id=plane.plane_id)
            for plane in self._board_planes(state, seat_id)
        )
        return tuple(choices)

    def _can_fly(self, plane: Plane) -> bool:
        return plane.step == board.SHORTCUT_STEP

    def _can_jump(self, state: AeroplaneState, plane: Plane) -> bool:
        return (
            state.pending_arrival == "step"
            and plane.step is not None
            and plane.step != board.SHORTCUT_STEP
            and board.is_own_color_ring_step(plane.step)
        )

    def _chain_choices(self, state: AeroplaneState, seat_id: str) -> tuple[AeroplaneAction, ...]:
        if state.pending_plane_id is None:
            return ()
        plane = self._find_plane(state, seat_id, state.pending_plane_id)
        choices: list[AeroplaneAction] = []
        if self._can_fly(plane):
            choices.append(FlyShortcutAction(plane_id=plane.plane_id))
        elif self._can_jump(state, plane):
            choices.append(JumpFourAction(plane_id=plane.plane_id))
        choices.append(EndMoveAction())
        return tuple(choices)

    def _next_seat(self, state: AeroplaneState, seat_id: str) -> str:
        order = state.seat_order
        return order[(order.index(cast(SeatId, seat_id)) + 1) % len(order)]

    def _end_turn(self, state: AeroplaneState, planes: tuple[Plane, ...]) -> AeroplaneState:
        return state.model_copy(
            update={
                "planes": planes,
                "current_seat_id": self._next_seat(state, state.current_seat_id or ""),
                "phase": "awaiting_roll",
                "dice": None,
                "consecutive_sixes": 0,
                "pending_plane_id": None,
                "pending_arrival": None,
            }
        )

    def _reroll(self, state: AeroplaneState, planes: tuple[Plane, ...]) -> AeroplaneState:
        # 掷到 6 后回到掷骰步骤，同一行动者继续，连续 6 计数保留。
        return state.model_copy(
            update={
                "planes": planes,
                "phase": "awaiting_roll",
                "dice": None,
                "pending_plane_id": None,
                "pending_arrival": None,
            }
        )

    def _finish_move(
        self, state: AeroplaneState, planes: tuple[Plane, ...], dice: int | None
    ) -> AeroplaneState:
        if dice == 6:
            return self._reroll(state, planes)
        return self._end_turn(state, planes)

    def _home_result(self, planes: tuple[Plane, ...], seat_id: str) -> AeroplaneResult | None:
        own = [plane for plane in planes if plane.seat_id == seat_id]
        if all(plane.step == board.HOME_STEP for plane in own):
            return AeroplaneResult(winner_seat_id=cast(SeatId, seat_id))
        return None

    def _resolve_arrival(
        self,
        state: AeroplaneState,
        planes: tuple[Plane, ...],
        seat_id: str,
        plane_id: int,
        arrival: str,
    ) -> AeroplaneState:
        plane = self._find_plane(state.model_copy(update={"planes": planes}), seat_id, plane_id)
        step = plane.step
        if step is None:
            raise GameError("illegal_action", "The plane is not on the board")
        # 只有本色虚线格，或「踏上」本色普通格才需要进入连锁；其余落点直接结束本次移动。
        if step == board.SHORTCUT_STEP or (
            board.is_own_color_ring_step(step) and arrival == "step"
        ):
            return state.model_copy(
                update={
                    "planes": planes,
                    "phase": "awaiting_chain",
                    "pending_plane_id": plane_id,
                    "pending_arrival": arrival,
                }
            )
        return self._finish_move(state, planes, state.dice)

    def _transition(
        self, state: AeroplaneState, events: list[AeroplaneActionOutcome]
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        return RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome](
            state=state, result=events[0], events=tuple(events)
        )

    def _roll(
        self, state: AeroplaneState, seat_id: str
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_roll":
            raise GameError("illegal_action", "The turn is not waiting for a roll")
        dice = cast(Dice, self._random.randint(1, 6))
        sixes = state.consecutive_sixes + 1 if dice == 6 else 0
        events: list[AeroplaneActionOutcome] = [
            DiceRolled(seat_id=cast(SeatId, seat_id), dice=dice)
        ]
        if sixes >= 3:
            if self._board_planes(state, seat_id):
                return self._transition(
                    state.model_copy(
                        update={
                            "phase": "awaiting_penalty",
                            "dice": dice,
                            "consecutive_sixes": sixes,
                        }
                    ),
                    events,
                )
            return self._transition(self._end_turn(state, state.planes), events)
        if not self._action_choices(state, seat_id, dice):
            return self._transition(self._end_turn(state, state.planes), events)
        return self._transition(
            state.model_copy(
                update={"phase": "awaiting_action", "dice": dice, "consecutive_sixes": sixes}
            ),
            events,
        )

    def _take_off(
        self, state: AeroplaneState, seat_id: str, action: TakeOffAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_action" or state.dice != 6:
            raise GameError("illegal_action", "Take-off needs a six")
        plane = self._find_plane(state, seat_id, action.plane_id)
        if plane.step is not None:
            raise GameError("illegal_action", "The plane has already taken off")
        planes = self._set_plane(state.planes, seat_id, action.plane_id, 0)
        events: list[AeroplaneActionOutcome] = [
            PlaneTookOff(seat_id=cast(SeatId, seat_id), plane_id=action.plane_id)
        ]
        # 起飞按到达处理：站在起飞处格上的对方棋子全部返回机场。
        planes, captured = self._capture(planes, seat_id, board.ring_cell(cast(SeatId, seat_id), 0))
        events.extend(captured)
        return self._transition(self._finish_move(state, planes, state.dice), events)

    def _move(
        self, state: AeroplaneState, seat_id: str, action: MovePlaneAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_action" or state.dice is None:
            raise GameError("illegal_action", "There is no dice to move with")
        plane = self._find_plane(state, seat_id, action.plane_id)
        if plane.step is None or plane.step >= board.HOME_STEP:
            raise GameError("illegal_action", "The plane is not on the board")
        target = plane.step + state.dice
        if target > board.HOME_STEP:
            # 归航道视为大箭头，超出终点时在终点反弹后回退。
            target = 2 * board.HOME_STEP - target
        planes = self._set_plane(state.planes, seat_id, action.plane_id, target)
        events: list[AeroplaneActionOutcome] = [
            PlaneWalked(
                seat_id=cast(SeatId, seat_id),
                plane_id=action.plane_id,
                from_step=plane.step,
                to_step=target,
            )
        ]
        if target <= board.LAST_RING_STEP:
            planes, captured = self._capture(
                planes, seat_id, board.ring_cell(cast(SeatId, seat_id), target)
            )
            events.extend(captured)
        if target == board.HOME_STEP and (result := self._home_result(planes, seat_id)) is not None:
            return self._transition(
                state.model_copy(
                    update={
                        "planes": planes,
                        "phase": "finished",
                        "current_seat_id": None,
                        "result": result,
                        "pending_plane_id": None,
                        "pending_arrival": None,
                    }
                ),
                events,
            )
        return self._transition(
            self._resolve_arrival(state, planes, seat_id, action.plane_id, "step"), events
        )

    def _jump(
        self, state: AeroplaneState, seat_id: str, action: JumpFourAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_chain" or state.pending_plane_id != action.plane_id:
            raise GameError("illegal_action", "This plane cannot jump now")
        plane = self._find_plane(state, seat_id, action.plane_id)
        if not self._can_jump(state, plane) or plane.step is None:
            raise GameError("illegal_action", "This plane cannot jump four")
        target = plane.step + 4
        planes = self._set_plane(state.planes, seat_id, action.plane_id, target)
        events: list[AeroplaneActionOutcome] = [
            PlaneJumped(
                seat_id=cast(SeatId, seat_id),
                plane_id=action.plane_id,
                from_step=plane.step,
                to_step=target,
            )
        ]
        if target <= board.LAST_RING_STEP:
            planes, captured = self._capture(
                planes, seat_id, board.ring_cell(cast(SeatId, seat_id), target)
            )
            events.extend(captured)
        return self._transition(
            self._resolve_arrival(state, planes, seat_id, action.plane_id, "jump"), events
        )

    def _fly(
        self, state: AeroplaneState, seat_id: str, action: FlyShortcutAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_chain" or state.pending_plane_id != action.plane_id:
            raise GameError("illegal_action", "This plane cannot fly now")
        plane = self._find_plane(state, seat_id, action.plane_id)
        if not self._can_fly(plane) or plane.step is None:
            raise GameError("illegal_action", "This plane is not on the shortcut")
        target = board.SHORTCUT_LANDING_STEP
        planes = self._set_plane(state.planes, seat_id, action.plane_id, target)
        events: list[AeroplaneActionOutcome] = [
            PlaneFlew(
                seat_id=cast(SeatId, seat_id),
                plane_id=action.plane_id,
                from_step=plane.step,
                to_step=target,
            )
        ]
        planes, captured = self._capture(
            planes, seat_id, board.ring_cell(cast(SeatId, seat_id), target)
        )
        events.extend(captured)
        planes, crossing = self._crossing_capture(planes, seat_id)
        events.extend(crossing)
        arrival = state.pending_arrival if state.pending_arrival is not None else "jump"
        return self._transition(
            self._resolve_arrival(state, planes, seat_id, action.plane_id, arrival), events
        )

    def _end_move(
        self, state: AeroplaneState, seat_id: str
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_chain" or state.pending_plane_id is None:
            raise GameError("illegal_action", "There is no move to end")
        events: list[AeroplaneActionOutcome] = [
            MoveEnded(seat_id=cast(SeatId, seat_id), plane_id=state.pending_plane_id)
        ]
        return self._transition(self._finish_move(state, state.planes, state.dice), events)

    def _penalty(
        self, state: AeroplaneState, seat_id: str, action: ReturnPenaltyAction
    ) -> RuleTransition[AeroplaneState, AeroplaneActionOutcome, AeroplaneActionOutcome]:
        if state.phase != "awaiting_penalty":
            raise GameError("illegal_action", "There is no penalty to settle")
        plane = self._find_plane(state, seat_id, action.plane_id)
        if plane.step is None or plane.step >= board.HOME_STEP:
            raise GameError("illegal_action", "The plane is not on the board")
        planes = self._set_plane(state.planes, seat_id, action.plane_id, None)
        events: list[AeroplaneActionOutcome] = [
            PlaneSentBack(seat_id=cast(SeatId, seat_id), plane_id=action.plane_id, reason="penalty")
        ]
        return self._transition(self._end_turn(state, planes), events)
