import { describe, expect, it } from 'vitest';
import {
  BASE_ORIGIN,
  BASE_SIZE,
  HOMESTRETCH,
  HOME_STEP,
  RING_CELLS,
  SEAT_ORDER,
  SHORTCUT_LANDING_STEP,
  SHORTCUT_STEP,
  TAKEOFF_CELL,
  TRACK_LENGTH,
  advanceStep,
  baseSlot,
  cellCenter,
  planeSpot,
  ringCellCenter,
  ringCellIndex,
  seatOfCell,
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

  it('外圈是四角机场之外的一条闭合顺时针回路', () => {
    expect(RING_CELLS.some(inBase)).toBe(false);
    expect(totalTurning()).toBe(360);
  });

  it('颜色按红黄蓝绿每 4 格循环，每色 13 格', () => {
    RING_CELLS.forEach((_, index) => {
      expect(seatOfCell(index)).toBe(SEAT_ORDER[index % 4]);
    });
    SEAT_ORDER.forEach((seat) => {
      expect(RING_CELLS.filter((_, index) => seatOfCell(index) === seat)).toHaveLength(13);
    });
  });

  it('四色起飞处相隔 13 格，各占一条跑道尖端', () => {
    const takeoffs = SEAT_ORDER.map((seat) => RING_CELLS[TAKEOFF_CELL[seat]]!);
    expect(takeoffs).toEqual([
      [7, 0],
      [14, 7],
      [7, 14],
      [0, 7],
    ]);
    expect(TAKEOFF_CELL.yellow - TAKEOFF_CELL.red).toBe(13);
    expect(TAKEOFF_CELL.blue - TAKEOFF_CELL.yellow).toBe(13);
    expect(TAKEOFF_CELL.green - TAKEOFF_CELL.blue).toBe(13);
  });
});

describe('飞行棋归航道与落位', () => {
  it('归航道每色 6 格，自外圈末格斜向内接入中央', () => {
    SEAT_ORDER.forEach((seat) => {
      const stretch = HOMESTRETCH[seat];
      expect(stretch).toHaveLength(6);
      for (let i = 1; i < stretch.length; i += 1) {
        expect(chebyshev(stretch[i - 1]!, stretch[i]!)).toBe(1);
      }
      const lastRingCell = RING_CELLS[ringCellIndex(seat, 51)]!;
      expect(chebyshev(lastRingCell, stretch[0]!)).toBe(1);
      expect(chebyshev(RING_CELLS[TAKEOFF_CELL[seat]]!, stretch[0]!)).toBe(1);
      expect(chebyshev(stretch[5]!, [7, 7])).toBe(1);
    });
  });

  it('虚线捷径落在本色归航入口的对侧', () => {
    SEAT_ORDER.forEach((seat) => {
      const from = RING_CELLS[ringCellIndex(seat, SHORTCUT_STEP)]!;
      const to = RING_CELLS[ringCellIndex(seat, SHORTCUT_LANDING_STEP)]!;
      expect(chebyshev(from, to)).toBeGreaterThanOrEqual(10);
    });
  });

  it('step 落到对应外圈格、归航道与终点', () => {
    SEAT_ORDER.forEach((seat: SeatId) => {
      const takeoff = cellCenter(RING_CELLS[TAKEOFF_CELL[seat]]!);
      expect(planeSpot(seat, 1, 0)).toEqual({ ...takeoff, home: false });
      const lastRing = ringCellCenter(ringCellIndex(seat, 51));
      expect(planeSpot(seat, 2, 51)).toEqual({ ...lastRing, home: false });
      expect(planeSpot(seat, 3, 52)).toEqual({
        ...cellCenter(HOMESTRETCH[seat][0]!),
        home: false,
      });
      expect(planeSpot(seat, 4, 57)).toEqual({
        ...cellCenter(HOMESTRETCH[seat][5]!),
        home: false,
      });
    });
  });

  it('机场与完成的棋子停在同一停机位，完成态另有标记', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(planeSpot(seat, 3, null)).toEqual({ ...baseSlot(seat, 3), home: false });
      expect(planeSpot(seat, 3, HOME_STEP)).toEqual({ ...baseSlot(seat, 3), home: true });
    });
    const slots = SEAT_ORDER.map((seat) => baseSlot(seat, 1).x);
    expect(slots).toEqual([145, 685, 685, 145]);
  });

  it('归航道超出终点按 116 减目标反弹', () => {
    expect(advanceStep(56, 4)).toBe(56);
    expect(advanceStep(57, 6)).toBe(53);
    expect(advanceStep(51, 6)).toBe(57);
    expect(advanceStep(40, 3)).toBe(43);
  });
});
