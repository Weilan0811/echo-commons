from typing import Literal

SeatId = Literal["red", "yellow", "blue", "green"]
SEAT_ORDER: tuple[SeatId, ...] = ("red", "yellow", "blue", "green")
TRACK_LENGTH = 52
WAITING_STEP = -1
LAST_RING_STEP = 48
HOME_FIRST_STEP = 49
HOME_STEP = 55
SHORTCUT_STEP = 16
SHORTCUT_LANDING_STEP = 28
TAKEOFF_CELL: dict[SeatId, int] = {"red": 0, "yellow": 13, "blue": 26, "green": 39}


def can_jump_from(step: int) -> bool:
    # 归航入口引导飞机进入专属通道，不再提供外圈跳格。
    return 0 <= step < LAST_RING_STEP and step % 4 == 0


def ring_cell(seat_id: SeatId, step: int) -> int:
    return (TAKEOFF_CELL[seat_id] + step) % TRACK_LENGTH
