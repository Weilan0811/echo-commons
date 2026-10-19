// 飞行棋前端的棋盘几何：外圈 52 格、四座机场、四段归航道与中央终点在 15×15
// 网格上的坐标。格号与 step 的换算规则与后端 aeroplane/board.py 一致，位置只在这里定义。

export const BOARD_VIEW = 1000;
export const TILE = 60;
export const ORIGIN = 50;

export const SEAT_ORDER = ['red', 'yellow', 'blue', 'green'] as const;
export type SeatId = (typeof SEAT_ORDER)[number];

export const TRACK_LENGTH = 52;
export const LAST_RING_STEP = 51;
export const HOMESTRETCH_FIRST_STEP = 52;
export const HOME_STEP = 58;
export const SHORTCUT_STEP = 24;
export const SHORTCUT_LANDING_STEP = 48;
export const CROSSING_STEP = 54;
export const TAKEOFF_CELL: Record<SeatId, number> = { red: 0, yellow: 13, blue: 26, green: 39 };
// 对角席位用于虚线的交叉吃子：红↔蓝、黄↔绿。
export const DIAGONAL_SEAT: Record<SeatId, SeatId> = {
  red: 'blue',
  blue: 'red',
  yellow: 'green',
  green: 'yellow',
};

// 棋盘色是棋子与格子的物理色，与界面主题无关；三种深度分别用于本色格、
// 起飞处与归航道、机场底色。
export const SEAT_FILL: Record<SeatId, { cell: string; deep: string; soft: string }> = {
  red: { cell: '#c9483d', deep: '#a3342b', soft: '#e2a79e' },
  yellow: { cell: '#d29a25', deep: '#ab7611', soft: '#ecd29b' },
  blue: { cell: '#3f74c4', deep: '#2f5697', soft: '#a3bde8' },
  green: { cell: '#377f5b', deep: '#266043', soft: '#9ec7ae' },
};

export type Cell = readonly [number, number];

// 外圈 52 格按顺时针编号：0 号是红方起飞处，红→黄→蓝→绿 每 4 格循环。
// 四色起飞处正好相隔 13 格，落在各自跑道的尖端。
export const RING_CELLS: readonly Cell[] = [
  [7, 0], [8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [9, 6],
  [10, 6], [11, 6], [12, 6], [13, 6], [14, 6], [14, 7], [14, 8], [13, 8],
  [12, 8], [11, 8], [10, 8], [9, 8], [8, 9], [8, 10], [8, 11], [8, 12],
  [8, 13], [8, 14], [7, 14], [6, 14], [6, 13], [6, 12], [6, 11], [6, 10],
  [6, 9], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8], [0, 7],
  [0, 6], [1, 6], [2, 6], [3, 6], [4, 6], [5, 6], [6, 5], [6, 4],
  [6, 3], [6, 2], [6, 1], [6, 0],
];

// 归航道 6 格：入口紧接外圈最后一格，末格落在中央方形的一条边上。
export const HOMESTRETCH: Record<SeatId, readonly Cell[]> = {
  red: [[7, 1], [7, 2], [7, 3], [7, 4], [7, 5], [7, 6]],
  yellow: [[13, 7], [12, 7], [11, 7], [10, 7], [9, 7], [8, 7]],
  blue: [[7, 13], [7, 12], [7, 11], [7, 10], [7, 9], [7, 8]],
  green: [[1, 7], [2, 7], [3, 7], [4, 7], [5, 7], [6, 7]],
};

// 机场是四角 6×6 区域：红左上、黄右上、蓝右下、绿左下。
export const BASE_ORIGIN: Record<SeatId, Cell> = {
  red: [0, 0],
  yellow: [9, 0],
  blue: [9, 9],
  green: [0, 9],
};
export const BASE_SIZE = 6;

const SLOT_OFFSETS = [
  { x: -85, y: -85 },
  { x: 85, y: -85 },
  { x: -85, y: 85 },
  { x: 85, y: 85 },
] as const;

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

// 前进后的落点：归航道超出终点时按「116 - 目标」反弹，与规则文档一致。
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

export type PlaneSpot = { x: number; y: number; home: boolean };

// 未起飞的棋子在机场停机位；到达终点的棋子按规则翻面回到原停机位，这里用 home 标记。
export function planeSpot(seat: SeatId, planeId: number, step: number | null): PlaneSpot {
  if (step === null) return { ...baseSlot(seat, planeId), home: false };
  if (step >= HOME_STEP) return { ...baseSlot(seat, planeId), home: true };
  if (step <= LAST_RING_STEP) return { ...ringCellCenter(ringCellIndex(seat, step)), home: false };
  return { ...cellCenter(HOMESTRETCH[seat][step - HOMESTRETCH_FIRST_STEP]!), home: false };
}
