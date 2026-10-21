import { describe, expect, it } from 'vitest';
import {
  BASE_ORIGIN,
  BASE_SIZE,
  HOMESTRETCH,
  HOMESTRETCH_FIRST_STEP,
  HOME_STEP,
  LAST_RING_STEP,
  ORIGIN,
  RING_CELLS,
  SEAT_ORDER,
  SHORTCUT_LANDING_STEP,
  SHORTCUT_STEP,
  TAKEOFF_CELL,
  TILE,
  TRACK_LENGTH,
  WAITING_STEP,
  advanceStep,
  baseSlot,
  cellCenter,
  planeSpot,
  ringCellCenter,
  ringCellIndex,
  seatOfCell,
  waitingSpot,
  type Cell,
  type SeatId,
} from './coordinates';

const chebyshev = (a: Cell, b: Cell) => Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1]));

function inBase(cell: Cell) {
  return SEAT_ORDER.some((seat) => {
    const [col, row] = BASE_ORIGIN[seat];
    return (
      cell[0] >= col &&
      cell[0] < col + BASE_SIZE &&
      cell[1] >= row &&
      cell[1] < row + BASE_SIZE
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

  it('四色起飞处相隔 13 格，紧贴自家机场，颜色都是本家颜色', () => {
    const takeoffs = SEAT_ORDER.map((seat) => RING_CELLS[TAKEOFF_CELL[seat]]!);
    expect(takeoffs).toEqual([
      [10, 0],
      [14, 10],
      [4, 14],
      [0, 4],
    ]);
    expect(TAKEOFF_CELL.yellow - TAKEOFF_CELL.red).toBe(13);
    expect(TAKEOFF_CELL.blue - TAKEOFF_CELL.yellow).toBe(13);
    expect(TAKEOFF_CELL.green - TAKEOFF_CELL.blue).toBe(13);
    // 机场与起飞格紧邻：起飞格贴着自家机场的一条边。
    SEAT_ORDER.forEach((seat) => {
      const [col, row] = BASE_ORIGIN[seat];
      const takeoff = RING_CELLS[TAKEOFF_CELL[seat]]!;
      const adjacent = (cell: Cell) =>
        cell[0] >= col - 1 &&
        cell[0] < col + BASE_SIZE + 1 &&
        cell[1] >= row - 1 &&
        cell[1] < row + BASE_SIZE + 1;
      expect(adjacent(takeoff)).toBe(true);
      expect(seatOfCell(TAKEOFF_CELL[seat])).toBe(seat);
    });
  });

  it('归航入口在边正中格，位于起飞格沿行进方向后退 3 格', () => {
    const entrances = SEAT_ORDER.map((seat) => RING_CELLS[ringCellIndex(seat, LAST_RING_STEP)]!);
    expect(entrances).toEqual([
      [7, 0],
      [14, 7],
      [7, 14],
      [0, 7],
    ]);
    SEAT_ORDER.forEach((seat) => {
      expect(LAST_RING_STEP).toBe(TRACK_LENGTH - 3);
      expect(HOMESTRETCH_FIRST_STEP).toBe(LAST_RING_STEP + 1);
      expect(HOME_STEP).toBe(56);
    });
  });

  it('相邻两个归航入口之间正好隔 12 格', () => {
    for (let i = 0; i < SEAT_ORDER.length; i += 1) {
      const here = ringCellIndex(SEAT_ORDER[i]!, LAST_RING_STEP);
      const next = ringCellIndex(SEAT_ORDER[(i + 1) % SEAT_ORDER.length]!, LAST_RING_STEP);
      const between = (next - here + TRACK_LENGTH) % TRACK_LENGTH - 1;
      expect(between).toBe(12);
    }
  });
});

describe('飞行棋归航道与落位', () => {
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

  it('虚线捷径飞越 12 格，两端同色，并斜切过对角家的机场角', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(SHORTCUT_LANDING_STEP[seat] - SHORTCUT_STEP[seat]).toBe(12);
      const fromIndex = ringCellIndex(seat, SHORTCUT_STEP[seat]);
      const toIndex = ringCellIndex(seat, SHORTCUT_LANDING_STEP[seat]);
      // 捷径两端同色（与自家起飞格同相位）。
      expect(seatOfCell(toIndex)).toBe(seatOfCell(fromIndex));
      expect(fromIndex % 4).toBe(TAKEOFF_CELL[seat] % 4);
      // 斜切段的中点落在对角家的机场范围内。
      const from = cellCenter(RING_CELLS[fromIndex]!);
      const to = cellCenter(RING_CELLS[toIndex]!);
      const diagonal = SEAT_ORDER[(SEAT_ORDER.indexOf(seat) + 2) % SEAT_ORDER.length]!;
      const [col, row] = BASE_ORIGIN[diagonal];
      const minX = ORIGIN + col * TILE;
      const minY = ORIGIN + row * TILE;
      const maxX = minX + BASE_SIZE * TILE;
      const maxY = minY + BASE_SIZE * TILE;
      const midX = (from.x + to.x) / 2;
      const midY = (from.y + to.y) / 2;
      expect(midX).toBeGreaterThan(minX);
      expect(midX).toBeLessThan(maxX);
      expect(midY).toBeGreaterThan(minY);
      expect(midY).toBeLessThan(maxY);
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

  it('机场与完成的棋子停在同一停机位，待飞位在机场平台角上', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(planeSpot(seat, 3, null)).toEqual({ ...baseSlot(seat, 3), home: false });
      expect(planeSpot(seat, 3, HOME_STEP)).toEqual({ ...baseSlot(seat, 3), home: true });
    });
    const slots = SEAT_ORDER.map((seat) => baseSlot(seat, 1).x);
    expect(slots).toEqual([728, 728, 188, 188]);
    const gates = SEAT_ORDER.map((seat) => waitingSpot(seat));
    expect(gates).toEqual([
      { x: 690, y: 150 },
      { x: 850, y: 690 },
      { x: 310, y: 850 },
      { x: 150, y: 310 },
    ]);
  });

  it('归航道超出终点按 112 减目标反弹', () => {
    expect(advanceStep(53, 5)).toBe(54);
    expect(advanceStep(54, 6)).toBe(52);
    expect(advanceStep(LAST_RING_STEP, 6)).toBe(55);
    expect(advanceStep(40, 3)).toBe(43);
    expect(advanceStep(WAITING_STEP, 1)).toBe(0);
    expect(advanceStep(WAITING_STEP, 6)).toBe(5);
  });
});
