// 飞行棋前端的棋盘几何：外圈 52 格、四座机场、四段归航道与中央终点在 15×15
// 网格上的坐标。格号与 step 的换算规则与后端 aeroplane/board.py 一致，位置只在这里定义。

export const BOARD_VIEW = 1000;
export const TILE = 60;
export const ORIGIN = 50;

export const SEAT_ORDER = ['red', 'yellow', 'blue', 'green'] as const;
export type SeatId = (typeof SEAT_ORDER)[number];

export const TRACK_LENGTH = 52;
// 归航入口在起飞格沿行进方向后退 3 格、落在边正中格，是外圈路径的最后一格。
export const LAST_RING_STEP = TRACK_LENGTH - 3;
export const HOMESTRETCH_FIRST_STEP = LAST_RING_STEP + 1;
export const HOME_STEP = HOMESTRETCH_FIRST_STEP + 6;
// 掷 6 起飞的棋子先停在机场出口的待飞位，再掷按点数前进（掷 1 恰好踏上起飞格）。
export const WAITING_STEP = -1;
// 每色一个虚线捷径格：位于对角家归航入口之后、与自家起飞格同色；
// 沿虚线飞越 12 格，落在前方同色格上。
export const SHORTCUT_STEP: Record<SeatId, number> = { red: 24, yellow: 24, blue: 24, green: 24 };
export const SHORTCUT_LANDING_STEP: Record<SeatId, number> = {
  red: 36,
  yellow: 36,
  blue: 36,
  green: 36,
};
export const TAKEOFF_CELL: Record<SeatId, number> = { red: 0, yellow: 13, blue: 26, green: 39 };

// 棋盘色是棋子与格子的物理色，与界面主题无关；三种深度分别用于本色格、
// 起飞处与归航道、机场底色。
export const SEAT_FILL: Record<SeatId, { cell: string; deep: string; soft: string }> = {
  red: { cell: '#c9483d', deep: '#a3342b', soft: '#e2a79e' },
  yellow: { cell: '#d29a25', deep: '#ab7611', soft: '#ecd29b' },
  blue: { cell: '#3f74c4', deep: '#2f5697', soft: '#a3bde8' },
  green: { cell: '#377f5b', deep: '#266043', soft: '#9ec7ae' },
};

export type Cell = readonly [number, number];

// 外圈 52 格按顺时针编号：0 号是红方起飞处（紧贴右上机场），红→黄→蓝→绿沿环
// 循环，四色起飞处相隔 13 格。四个角格不参与跑道，因此四边各有 13 格、相邻
// 归航入口之间正好隔 12 格；起飞格颜色由循环决定，正好都是本家颜色。
export const RING_CELLS: readonly Cell[] = [
  [10, 0], [11, 0], [12, 0], [13, 0],
  [14, 1], [14, 2], [14, 3], [14, 4], [14, 5], [14, 6], [14, 7], [14, 8], [14, 9],
  [14, 10], [14, 11], [14, 12], [14, 13],
  [13, 14], [12, 14], [11, 14], [10, 14], [9, 14], [8, 14], [7, 14], [6, 14], [5, 14],
  [4, 14], [3, 14], [2, 14], [1, 14],
  [0, 13], [0, 12], [0, 11], [0, 10], [0, 9], [0, 8], [0, 7], [0, 6], [0, 5], [0, 4],
  [0, 3], [0, 2], [0, 1],
  [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [7, 0], [8, 0], [9, 0],
];

// 归航道 6 格：入口是外圈边正中格，末格落在中央方形的一条边上。
export const HOMESTRETCH: Record<SeatId, readonly Cell[]> = {
  red: [[7, 1], [7, 2], [7, 3], [7, 4], [7, 5], [7, 6]],
  yellow: [[13, 7], [12, 7], [11, 7], [10, 7], [9, 7], [8, 7]],
  blue: [[7, 13], [7, 12], [7, 11], [7, 10], [7, 9], [7, 8]],
  green: [[1, 7], [2, 7], [3, 7], [4, 7], [5, 7], [6, 7]],
};

// 机场是四角 4×4 区域：红右上、黄右下、蓝左下、绿左上。
export const BASE_ORIGIN: Record<SeatId, Cell> = {
  red: [10, 1],
  yellow: [10, 10],
  blue: [1, 10],
  green: [1, 1],
};
export const BASE_SIZE = 4;

const SLOT_OFFSETS = [
  { x: -42, y: -42 },
  { x: 42, y: -42 },
  { x: -42, y: 42 },
  { x: 42, y: 42 },
] as const;

// 待飞区（机场出口）在平台朝向起飞格的角上，用相对机场中心的偏移表示。
const WAITING_OFFSET: Record<SeatId, readonly [number, number]> = {
  red: [-80, -80],
  yellow: [80, -80],
  blue: [80, 80],
  green: [-80, 80],
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
  const [dx, dy] = WAITING_OFFSET[seat];
  const center = baseCenter(seat);
  return { x: center.x + dx, y: center.y + dy };
}

export type PlaneSpot = { x: number; y: number; home: boolean };

// 未起飞的棋子在机场停机位；待飞位的棋子停在机场出口；到达终点的棋子按规则
// 翻面回到原停机位，这里用 home 标记。
export function planeSpot(seat: SeatId, planeId: number, step: number | null): PlaneSpot {
  if (step === null) return { ...baseSlot(seat, planeId), home: false };
  if (step >= HOME_STEP) return { ...baseSlot(seat, planeId), home: true };
  if (step === WAITING_STEP) return { ...waitingSpot(seat), home: false };
  if (step <= LAST_RING_STEP) return { ...ringCellCenter(ringCellIndex(seat, step)), home: false };
  return { ...cellCenter(HOMESTRETCH[seat][step - HOMESTRETCH_FIRST_STEP]!), home: false };
}
