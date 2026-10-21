import { describe, expect, it } from 'vitest';
import {
  BASE_ORIGIN,
  BASE_SIZE,
  HOMESTRETCH,
  HOMESTRETCH_FIRST_STEP,
  HOME_STEP,
  LAST_RING_STEP,
  RING_CELLS,
  SEAT_ORDER,
  SHORTCUT_LANDING_STEP,
  SHORTCUT_STEP,
  TAKEOFF_CELL,
  TILE,
  TRACK_LENGTH,
  WAITING_STEP,
  advanceStep,
  baseBounds,
  baseSlot,
  cellCenter,
  planeSpot,
  ringCellCenter,
  ringCellIndex,
  seatOfCell,
  rotateCell,
  shortcutLink,
  waitingSpot,
  type Cell,
  type SeatId,
} from './coordinates';

const chebyshev = (a: Cell, b: Cell) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));

function inBase(cell: Cell) {
  return SEAT_ORDER.some((seat) => {
    const [col, row] = BASE_ORIGIN[seat];
    return (
      cell[0] >= col && cell[0] < col + BASE_SIZE && cell[1] >= row && cell[1] < row + BASE_SIZE
    );
  });
}

// 转角总和用于确认外圈是一条闭合的顺时针回路：凸角 +90°、凹角 −90°。
function totalTurning() {
  let total = 0;
  for (let i = 0; i < RING_CELLS.length; i += 1) {
    const prev = RING_CELLS[(i - 1 + RING_CELLS.length) % RING_CELLS.length]!;
    const here = RING_CELLS[i]!;
    const next = RING_CELLS[(i + 1) % RING_CELLS.length]!;
    const first = [here[0] - prev[0], here[1] - prev[1]] as const;
    const second = [next[0] - here[0], next[1] - here[1]] as const;
    const cross = first[0] * second[1] - first[1] * second[0];
    const dot = first[0] * second[0] + first[1] * second[1];
    if (cross === 0 && dot === 1) continue;
    expect(dot).not.toBe(-1);
    total += cross > 0 ? (dot === 0 ? 90 : 45) : dot === 0 ? -90 : -45;
  }
  return total;
}

describe('飞行棋外圈几何', () => {
  it('外圈 52 格互不重复，相邻格号在网格上相接', () => {
    expect(RING_CELLS).toHaveLength(TRACK_LENGTH);
    const seen = new Set(RING_CELLS.map((cell) => `${cell[0]}:${cell[1]}`));
    expect(seen.size).toBe(TRACK_LENGTH);
    for (let i = 0; i < RING_CELLS.length; i += 1) {
      const next = RING_CELLS[(i + 1) % RING_CELLS.length]!;
      expect(chebyshev(RING_CELLS[i]!, next)).toBe(1);
    }
  });

  it('外圈是四角机场之外的一条闭合顺时针回路，四个角格不参与跑道', () => {
    expect(RING_CELLS.some(inBase)).toBe(false);
    expect(totalTurning()).toBe(360);
    for (const corner of [
      [0, 0],
      [14, 0],
      [0, 14],
      [14, 14],
    ] as const) {
      expect(RING_CELLS.some((cell) => cell[0] === corner[0] && cell[1] === corner[1])).toBe(false);
    }
  });

  it('颜色按红黄蓝绿每 4 格循环，每色 13 格', () => {
    RING_CELLS.forEach((_, index) => {
      expect(seatOfCell(index)).toBe(SEAT_ORDER[index % 4]);
    });
    SEAT_ORDER.forEach((seat) => {
      expect(RING_CELLS.filter((_, index) => seatOfCell(index) === seat)).toHaveLength(13);
    });
  });

  it('四色起飞处相隔 13 格，待飞位连向同色起飞格', () => {
    const takeoffs = SEAT_ORDER.map((seat) => RING_CELLS[TAKEOFF_CELL[seat]]!);
    expect(takeoffs).toEqual([
      [10, 1],
      [13, 10],
      [4, 13],
      [1, 4],
    ]);
    expect(TAKEOFF_CELL.yellow - TAKEOFF_CELL.red).toBe(13);
    expect(TAKEOFF_CELL.blue - TAKEOFF_CELL.yellow).toBe(13);
    expect(TAKEOFF_CELL.green - TAKEOFF_CELL.blue).toBe(13);
    SEAT_ORDER.forEach((seat) => {
      const takeoff = ringCellCenter(TAKEOFF_CELL[seat]);
      const waiting = waitingSpot(seat);
      expect(Math.hypot(takeoff.x - waiting.x, takeoff.y - waiting.y)).toBe(TILE);
      expect(seatOfCell(TAKEOFF_CELL[seat])).toBe(seat);
    });
  });

  it('归航入口在边正中格，位于起飞格沿行进方向后退 4 格，入口与本家通道同色', () => {
    const entrances = SEAT_ORDER.map((seat) => RING_CELLS[ringCellIndex(seat, LAST_RING_STEP)]!);
    expect(entrances).toEqual([
      [7, 0],
      [14, 7],
      [7, 14],
      [0, 7],
    ]);
    SEAT_ORDER.forEach((seat) => {
      expect(LAST_RING_STEP).toBe(TRACK_LENGTH - 4);
      expect(HOMESTRETCH_FIRST_STEP).toBe(LAST_RING_STEP + 1);
      expect(HOME_STEP).toBe(55);
      expect(seatOfCell(ringCellIndex(seat, LAST_RING_STEP))).toBe(seat);
    });
  });

  it('相邻两个归航入口之间正好隔 12 格', () => {
    for (let i = 0; i < SEAT_ORDER.length; i += 1) {
      const here = ringCellIndex(SEAT_ORDER[i]!, LAST_RING_STEP);
      const next = ringCellIndex(SEAT_ORDER[(i + 1) % SEAT_ORDER.length]!, LAST_RING_STEP);
      const between = ((next - here + TRACK_LENGTH) % TRACK_LENGTH) - 1;
      expect(between).toBe(12);
    }
  });
});

describe('飞行棋归航道与落位', () => {
  it('新捷径沿直线跨过对家的归航道，两端均为本家颜色', () => {
    SEAT_ORDER.forEach((seat, turn) => {
      const { from, to } = shortcutLink(seat);
      const opposite = SEAT_ORDER[(turn + 2) % 4]!;
      expect({ x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 }).toEqual(
        cellCenter(HOMESTRETCH[opposite][2]!),
      );
      expect(seatOfCell(ringCellIndex(seat, SHORTCUT_STEP[seat]))).toBe(seat);
      expect(seatOfCell(ringCellIndex(seat, SHORTCUT_LANDING_STEP[seat]))).toBe(seat);
    });
  });

  it('归航道每色 6 格，自入口正交接入中央', () => {
    SEAT_ORDER.forEach((seat) => {
      const stretch = HOMESTRETCH[seat];
      expect(stretch).toHaveLength(6);
      for (let i = 1; i < stretch.length; i += 1) {
        expect(chebyshev(stretch[i - 1]!, stretch[i]!)).toBe(1);
      }
      const entrance = RING_CELLS[ringCellIndex(seat, LAST_RING_STEP)]!;
      expect(chebyshev(entrance, stretch[0]!)).toBe(1);
      expect(stretch[5]!.includes(7)).toBe(true);
      expect(chebyshev(stretch[5]!, [7, 7])).toBe(1);
    });
  });

  it('虚线捷径飞越 12 格，两端同色，完整线段与所有机场及待飞位分离', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(SHORTCUT_LANDING_STEP[seat] - SHORTCUT_STEP[seat]).toBe(12);
      const fromIndex = ringCellIndex(seat, SHORTCUT_STEP[seat]);
      const toIndex = ringCellIndex(seat, SHORTCUT_LANDING_STEP[seat]);
      expect(seatOfCell(toIndex)).toBe(seatOfCell(fromIndex));
      expect(fromIndex % 4).toBe(TAKEOFF_CELL[seat] % 4);
      const { from, to } = shortcutLink(seat);
      expect(from).toEqual(ringCellCenter(fromIndex));
      expect(to).toEqual(ringCellCenter(toIndex));
      SEAT_ORDER.forEach((airport) => {
        const { x, y, size } = baseBounds(airport);
        // 分离轴检查整条线段，机场外扩 12 像素，为线宽及方向标记保留距离。
        const corners = [
          [x - 12, y - 12],
          [x + size + 12, y - 12],
          [x + size + 12, y + size + 12],
          [x - 12, y + size + 12],
        ];
        const axes = [
          [1, 0],
          [0, 1],
          [to.y - from.y, from.x - to.x],
        ];
        const separated = axes.some(([ax, ay]) => {
          const line = [from.x * ax! + from.y * ay!, to.x * ax! + to.y * ay!];
          const box = corners.map(([cx, cy]) => cx! * ax! + cy! * ay!);
          return Math.max(...line) < Math.min(...box) || Math.max(...box) < Math.min(...line);
        });
        expect(separated, `${seat} 捷径与 ${airport} 机场分离`).toBe(true);
        const gate = waitingSpot(airport);
        const dx = to.x - from.x,
          dy = to.y - from.y;
        const t = Math.max(
          0,
          Math.min(1, ((gate.x - from.x) * dx + (gate.y - from.y) * dy) / (dx * dx + dy * dy)),
        );
        expect(Math.hypot(gate.x - from.x - t * dx, gate.y - from.y - t * dy)).toBeGreaterThan(30);
      });
    });
  });

  it('step 落到待飞位、外圈格、归航道与终点', () => {
    SEAT_ORDER.forEach((seat: SeatId) => {
      const takeoff = cellCenter(RING_CELLS[TAKEOFF_CELL[seat]]!);
      expect(planeSpot(seat, 1, 0)).toEqual({ ...takeoff, home: false });
      const lastRing = ringCellCenter(ringCellIndex(seat, LAST_RING_STEP));
      expect(planeSpot(seat, 2, LAST_RING_STEP)).toEqual({ ...lastRing, home: false });
      expect(planeSpot(seat, 3, HOMESTRETCH_FIRST_STEP)).toEqual({
        ...cellCenter(HOMESTRETCH[seat][0]!),
        home: false,
      });
      expect(planeSpot(seat, 4, HOME_STEP - 1)).toEqual({
        ...cellCenter(HOMESTRETCH[seat][5]!),
        home: false,
      });
      expect(planeSpot(seat, 1, WAITING_STEP)).toEqual({ ...waitingSpot(seat), home: false });
    });
  });

  it('机场与完成的棋子停在同一停机位，待飞位与停机位分离', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(planeSpot(seat, 3, null)).toEqual({ ...baseSlot(seat, 3), home: false });
      expect(planeSpot(seat, 3, HOME_STEP)).toEqual({ ...baseSlot(seat, 3), home: true });
    });
    const slots = SEAT_ORDER.map((seat) => baseSlot(seat, 1).x);
    expect(slots).toEqual([788, 788, 128, 128]);
    const gates = SEAT_ORDER.map((seat) => waitingSpot(seat));
    expect(gates).toEqual([
      { x: 620, y: 140 },
      { x: 860, y: 620 },
      { x: 380, y: 860 },
      { x: 140, y: 380 },
    ]);
  });

  it('跑道、归航道、机场和待飞位均按中心旋转保持四色一致', () => {
    for (let turn = 0; turn < 4; turn += 1) {
      const seat = SEAT_ORDER[turn]!;
      for (let index = 0; index < 13; index += 1)
        expect(RING_CELLS[turn * 13 + index]).toEqual(rotateCell(RING_CELLS[index]!, turn));
      expect(HOMESTRETCH[seat]).toEqual(HOMESTRETCH.red.map((cell) => rotateCell(cell, turn)));
      for (let plane = 1; plane <= 4; plane += 1) {
        const { x, y, size } = baseBounds(seat);
        const spot = baseSlot(seat, plane);
        expect(spot.x - 26).toBeGreaterThan(x);
        expect(spot.x + 26).toBeLessThan(x + size);
        expect(spot.y - 26).toBeGreaterThan(y);
        expect(spot.y + 26).toBeLessThan(y + size);
        expect(
          Math.hypot(spot.x - waitingSpot(seat).x, spot.y - waitingSpot(seat).y),
        ).toBeGreaterThan(54);
      }
    }
  });

  it('归航道超出终点按 110 减目标反弹', () => {
    expect(advanceStep(53, 5)).toBe(52);
    expect(advanceStep(54, 6)).toBe(50);
    expect(advanceStep(LAST_RING_STEP, 6)).toBe(54);
    expect(advanceStep(40, 3)).toBe(43);
    expect(advanceStep(WAITING_STEP, 1)).toBe(0);
    expect(advanceStep(WAITING_STEP, 6)).toBe(5);
  });
});
