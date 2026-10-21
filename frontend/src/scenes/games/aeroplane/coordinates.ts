// 逻辑格号沿用后端 board.py；展示坐标集中定义在 15×15 网格上。

export const BOARD_VIEW = 1000;
export const TILE = 60;
export const ORIGIN = 50;

export const SEAT_ORDER = ['red', 'yellow', 'blue', 'green'] as const;
export type SeatId = (typeof SEAT_ORDER)[number];

export const TRACK_LENGTH = 52;
export const WAITING_STEP = -1;
export const TAKEOFF_CELL: Record<SeatId, number> = { red: 0, yellow: 13, blue: 26, green: 39 };
export const LAST_RING_STEP = 48;
export const HOMESTRETCH_FIRST_STEP = 49;
export const HOME_STEP = 55;
export const SHORTCUT_STEP: Record<SeatId, number> = { red: 16, yellow: 16, blue: 16, green: 16 };
export const SHORTCUT_LANDING_STEP: Record<SeatId, number> = {
  red: 28,
  yellow: 28,
  blue: 28,
  green: 28,
};

// 棋盘色是棋子与格子的物理色，与界面主题无关；三种深度分别用于本色格、
// 起飞处与归航道、机场底色。
export const SEAT_FILL: Record<SeatId, { cell: string; deep: string; soft: string }> = {
  red: { cell: '#d94a45', deep: '#ad3436', soft: '#f4cfca' },
  yellow: { cell: '#e9ba35', deep: '#a87816', soft: '#fae9ac' },
  blue: { cell: '#398ac4', deep: '#246397', soft: '#c5e0ef' },
  green: { cell: '#439c64', deep: '#2a7048', soft: '#c9e5cc' },
};

export type Cell = readonly [number, number];

export function rotateCell([x, y]: Cell, turns: number): Cell {
  let cell: Cell = [x, y];
  for (let turn = 0; turn < turns; turn += 1) cell = [14 - cell[1], cell[0]];
  return cell;
}

// 每一段 13 格，绕中心旋转得到完整跑道。转角内收，为四角机场留出空间。
const TRACK_QUARTER: readonly Cell[] = [
  [10, 1],
  [10, 2],
  [10, 3],
  [11, 4],
  [12, 4],
  [13, 4],
  [14, 4],
  [14, 5],
  [14, 6],
  [14, 7],
  [14, 8],
  [14, 9],
  [14, 10],
];
export const RING_CELLS: readonly Cell[] = SEAT_ORDER.flatMap((_, turn) =>
  TRACK_QUARTER.map((cell) => rotateCell(cell, turn)),
);

// 归航道 6 格：入口是外圈边正中格，末格落在中央方形的一条边上。
export const HOMESTRETCH: Record<SeatId, readonly Cell[]> = {
  red: [
    [7, 1],
    [7, 2],
    [7, 3],
    [7, 4],
    [7, 5],
    [7, 6],
  ],
  yellow: [
    [13, 7],
    [12, 7],
    [11, 7],
    [10, 7],
    [9, 7],
    [8, 7],
  ],
  blue: [
    [7, 13],
    [7, 12],
    [7, 11],
    [7, 10],
    [7, 9],
    [7, 8],
  ],
  green: [
    [1, 7],
    [2, 7],
    [3, 7],
    [4, 7],
    [5, 7],
    [6, 7],
  ],
};

// 机场是四角 4×4 区域：红右上、黄右下、蓝左下、绿左上。
export const BASE_ORIGIN: Record<SeatId, Cell> = {
  red: [11, 0],
  yellow: [11, 11],
  blue: [0, 11],
  green: [0, 0],
};
export const BASE_SIZE = 4;
export const BASE_INSET = 32;
export const FINISH_CELL: Cell = [7, 7];

const SLOT_OFFSETS = [
  { x: -42, y: -42 },
  { x: 42, y: -42 },
  { x: -42, y: 42 },
  { x: 42, y: 42 },
] as const;

// 待飞位独立于机场与跑道，出口箭头连向本家起飞格。
const WAITING_CELLS: Record<SeatId, Cell> = {
  red: [9, 1],
  yellow: [13, 9],
  blue: [5, 13],
  green: [1, 5],
};

export function cellCenter(cell: Cell) {
  return { x: ORIGIN + cell[0] * TILE + TILE / 2, y: ORIGIN + cell[1] * TILE + TILE / 2 };
}

export function seatOfCell(index: number): SeatId {
  return SEAT_ORDER[index % SEAT_ORDER.length]!;
}

export function ringCellIndex(seat: SeatId, step: number) {
  return (TAKEOFF_CELL[seat] + step) % TRACK_LENGTH;
}

export function ringCellCenter(index: number) {
  return cellCenter(RING_CELLS[index]!);
}

// 前进后的落点：归航道超出终点时按「两倍终点减目标」反弹，与规则文档一致。
export function advanceStep(step: number, dice: number) {
  const target = step + dice;
  return target > HOME_STEP ? 2 * HOME_STEP - target : target;
}

export function baseCenter(seat: SeatId) {
  const [col, row] = BASE_ORIGIN[seat];
  return {
    x: ORIGIN + col * TILE + (BASE_SIZE * TILE) / 2,
    y: ORIGIN + row * TILE + (BASE_SIZE * TILE) / 2,
  };
}

export function baseSlot(seat: SeatId, planeId: number) {
  const center = baseCenter(seat);
  const offset = SLOT_OFFSETS[planeId - 1]!;
  return { x: center.x + offset.x, y: center.y + offset.y };
}

export function waitingSpot(seat: SeatId) {
  return cellCenter(WAITING_CELLS[seat]);
}

export function baseBounds(seat: SeatId) {
  const [x, y] = BASE_ORIGIN[seat];
  return {
    x: ORIGIN + x * TILE + BASE_INSET,
    y: ORIGIN + y * TILE + BASE_INSET,
    size: BASE_SIZE * TILE - BASE_INSET * 2,
  };
}

export function homeEntry(seat: SeatId) {
  return ringCellCenter(ringCellIndex(seat, LAST_RING_STEP));
}

export function shortcutLink(seat: SeatId) {
  return {
    from: ringCellCenter(ringCellIndex(seat, SHORTCUT_STEP[seat])),
    to: ringCellCenter(ringCellIndex(seat, SHORTCUT_LANDING_STEP[seat])),
  };
}

export type PlaneSpot = { x: number; y: number; home: boolean };

// 未起飞的棋子在机场停机位；待飞位的棋子停在机场出口；到达终点的棋子按规则
// 翻面回到原停机位，这里用 home 标记。
export function planeSpot(
  seat: SeatId,
  planeId: number,
  step: number | null,
): PlaneSpot {
  if (step === null) return { ...baseSlot(seat, planeId), home: false };
  if (step >= HOME_STEP) return { ...baseSlot(seat, planeId), home: true };
  if (step === WAITING_STEP) return { ...waitingSpot(seat), home: false };
  if (step <= LAST_RING_STEP)
    return { ...ringCellCenter(ringCellIndex(seat, step)), home: false };
  return { ...cellCenter(HOMESTRETCH[seat][step - HOMESTRETCH_FIRST_STEP]!), home: false };
}
