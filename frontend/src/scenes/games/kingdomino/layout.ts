import type { GameAction } from '@/api/games';

// 素材目录：地形贴图、皇冠与城堡沿用已交付文件，棋盘与地块外框由前端程序绘制。
const TEXTURE_DIR = '/assets/games/activity/kingdomino/textures';
const UI_DIR = '/assets/games/activity/kingdomino/ui';
const PIECE_DIR = '/assets/games/activity/kingdomino/pieces';

// 城堡素材只有红、黄、绿、蓝，粉席借用红色城堡作为同席标志。
const CASTLE_COLOR: Record<string, string> = {
  pink: 'red',
  yellow: 'yellow',
  green: 'green',
  blue: 'blue',
};

export type Direction = 'right' | 'down' | 'left' | 'up';
export const DIRECTIONS: readonly Direction[] = ['right', 'down', 'left', 'up'];

// B 格相对 A 格的模型坐标偏移；模型 y 轴向上，因此向下的偏移为负。
export const DIRECTION_OFFSET: Record<Direction, readonly [number, number]> = {
  right: [1, 0],
  down: [0, -1],
  left: [-1, 0],
  up: [0, 1],
};

export type PlaceAction = Extract<GameAction, { type: 'place_domino' }>;
export type Coord = { x: number; y: number };
export type PlacementGroup = { cell: Coord; directions: Direction[] };

export type Bounds = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  columns: number;
  rows: number;
};

export function terrainTexture(terrain: string): string {
  return `${TEXTURE_DIR}/terrain_${terrain}.svg`;
}

export function crownIcon(): string {
  return `${UI_DIR}/crown_gold.svg`;
}

export function castleIcon(seatId: string): string {
  return `${PIECE_DIR}/castle_${CASTLE_COLOR[seatId] ?? 'red'}.svg`;
}

export function coordKey(cell: Coord): string {
  return `${cell.x},${cell.y}`;
}

export function nextCoord(cell: Coord, direction: Direction): Coord {
  const [dx, dy] = DIRECTION_OFFSET[direction];
  return { x: cell.x + dx, y: cell.y + dy };
}

// 合法动作按 A 格坐标归组，方向按四向固定顺序排列，便于在同一落点上轮换朝向。
export function groupPlacements(actions: readonly PlaceAction[]): PlacementGroup[] {
  const groups = new Map<string, PlacementGroup>();
  for (const action of actions) {
    const key = `${action.cell_x},${action.cell_y}`;
    const group = groups.get(key);
    if (group) group.directions.push(action.direction);
    else
      groups.set(key, {
        cell: { x: action.cell_x, y: action.cell_y },
        directions: [action.direction],
      });
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      directions: DIRECTIONS.filter((direction) => group.directions.includes(direction)),
    }))
    .sort((left, right) => left.cell.x - right.cell.x || left.cell.y - right.cell.y);
}

export function boundsOf(points: readonly Coord[]): Bounds {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    minX,
    maxX,
    minY,
    maxY,
    columns: maxX - minX + 1,
    rows: maxY - minY + 1,
  };
}

// 保留所有合法落点，空余范围补成至少 5×5 的正方形，避免开局城堡被单独放大。
export function displayBounds(points: readonly Coord[]): Bounds {
  const bounds = boundsOf(points.length ? points : [{ x: 0, y: 0 }]);
  const size = Math.max(5, bounds.columns, bounds.rows);
  const minX = bounds.minX - Math.floor((size - bounds.columns) / 2);
  const minY = bounds.minY - Math.floor((size - bounds.rows) / 2);
  return {
    minX,
    minY,
    maxX: minX + size - 1,
    maxY: minY + size - 1,
    columns: size,
    rows: size,
  };
}

// 模型 y 轴向上、显示 y 轴向下，因此模型最大 y 落在第一行。
export function gridPosition(bounds: Bounds, cell: Coord): { column: number; row: number } {
  return { column: cell.x - bounds.minX, row: bounds.maxY - cell.y };
}
