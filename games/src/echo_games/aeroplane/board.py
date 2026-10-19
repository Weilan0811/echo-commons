from typing import Literal

SeatId = Literal["red", "yellow", "blue", "green"]

# 棋盘几何来自《飞行棋基础规则》第 3 节的全部项目决定，本模块是这些数值的唯一来源。
SEAT_ORDER: tuple[SeatId, ...] = ("red", "yellow", "blue", "green")
TRACK_LENGTH = 52
LAST_RING_STEP = TRACK_LENGTH - 1
HOMESTRETCH_LENGTH = 6
HOMESTRETCH_FIRST_STEP = TRACK_LENGTH
HOME_STEP = TRACK_LENGTH + HOMESTRETCH_LENGTH
TAKEOFF_CELL: dict[SeatId, int] = {"red": 0, "yellow": 13, "blue": 26, "green": 39}
SHORTCUT_STEP = 24
SHORTCUT_LANDING_STEP = 48
# 虚线交叉格是本色归航道第 3 格，对角色飞越时落在自己的对应格。
CROSSING_HOMESTRETCH_INDEX = 3
CROSSING_STEP = HOMESTRETCH_FIRST_STEP + CROSSING_HOMESTRETCH_INDEX - 1
DIAGONAL_SEAT: dict[SeatId, SeatId] = {
    "red": "blue",
    "blue": "red",
    "yellow": "green",
    "green": "yellow",
}


def ring_cell(seat_id: SeatId, step: int) -> int:
    # 外圈格号；只有外圈步数才有格号，归航道与终点不在外圈上。
    return (TAKEOFF_CELL[seat_id] + step) % TRACK_LENGTH


def is_own_color_ring_step(step: int) -> bool:
    # 本色格即本色的外圈格，等价于步数能被 4 整除且仍在外圈内。
    return 0 <= step <= LAST_RING_STEP and step % 4 == 0
