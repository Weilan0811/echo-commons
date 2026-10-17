export const BOARD_SIZE = 600;
export const GRID_ORIGIN = 48;
export const GRID_STEP = 36;

export function intersectionAt(x: number, y: number): { x: number; y: number } | null {
  const column = Math.round((x - GRID_ORIGIN) / GRID_STEP);
  const row = Math.round((y - GRID_ORIGIN) / GRID_STEP);
  if (column < 0 || column > 14 || row < 0 || row > 14) return null;
  return { x: column, y: row };
}

export function coordinateLabel(point: { x: number; y: number }): string {
  return `${String.fromCharCode(65 + point.x)}${point.y + 1}`;
}
