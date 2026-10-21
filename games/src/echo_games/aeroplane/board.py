from typing import Literal

SeatId = Literal["red", "yellow", "blue", "green"]

# 棋盘几何来自《飞行棋基础规则》第 3 节的全部项目决定，本模块是这些数值的唯一来源。
SEAT_ORDER: tuple[SeatId, ...] = ("red", "yellow", "blue", "green")
# 外圈是 15×15 网格最外一圈去掉四个角格后的 52 格矩形环，每边 13 格。
# 顺时针行进下四座机场位于红右上、黄右下、蓝左下、绿左上；四家起飞格沿环
# 相隔 13 格，各自紧贴自家机场，相邻归航入口之间正好隔 12 格。
TRACK_LENGTH = 52
# 归航入口在起飞格沿行进方向后退 3 格、恰好落在边正中格，是本席外圈路径的
# 最后一格；入口与起飞格之间的两格属于别家路径，本席不走。
LAST_RING_STEP = TRACK_LENGTH - 3
HOMESTRETCH_LENGTH = 6
HOMESTRETCH_FIRST_STEP = LAST_RING_STEP + 1
HOME_STEP = HOMESTRETCH_FIRST_STEP + HOMESTRETCH_LENGTH
# 掷 6 起飞的棋子先停在机场出口的待飞位（起飞格前一格的虚拟位置），
# 之后任意一次掷骰按点数前进，掷 1 恰好踏上起飞格。
WAITING_STEP = -1
TAKEOFF_CELL: dict[SeatId, int] = {"red": 0, "yellow": 13, "blue": 26, "green": 39}
# 每色一个虚线捷径格：位于对角家归航入口之后、与自家起飞格同色；沿虚线飞越
# 12 格，落在前方同色格上。四条虚线各自斜切过对角家的机场角。
SHORTCUT_STEP: dict[SeatId, int] = {"red": 24, "yellow": 24, "blue": 24, "green": 24}
SHORTCUT_LANDING_STEP: dict[SeatId, int] = {"red": 36, "yellow": 36, "blue": 36, "green": 36}


def ring_cell(seat_id: SeatId, step: int) -> int:
    # 外圈格号；只有外圈步数才有格号，归航道与终点不在外圈上。
    return (TAKEOFF_CELL[seat_id] + step) % TRACK_LENGTH


def is_takeoff_color_ring_step(seat_id: SeatId, step: int) -> bool:
    # 与自家起飞格同色的外圈格才提供跳四格连锁。四家起飞格相位固定：
    # 红蓝家的起飞格是红色格、黄绿家是蓝色格，该判定恒等于步数被 4 整除。
    if not (0 <= step <= LAST_RING_STEP):
        return False
    phase = len(SEAT_ORDER)
    return (TAKEOFF_CELL[seat_id] + step) % phase == TAKEOFF_CELL[seat_id] % phase
