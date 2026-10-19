import { describe, expect, it } from 'vitest';
import { boundsOf, groupPlacements, gridPosition, nextCoord, type PlaceAction } from './layout';

function place(cell_x: number, cell_y: number, direction: PlaceAction['direction']): PlaceAction {
  return { type: 'place_domino', cell_x, cell_y, direction };
}

describe('nextCoord', () => {
  it('按模型坐标给出 B 格偏移，向下为负 y', () => {
    expect(nextCoord({ x: 0, y: 0 }, 'right')).toEqual({ x: 1, y: 0 });
    expect(nextCoord({ x: 0, y: 0 }, 'left')).toEqual({ x: -1, y: 0 });
    expect(nextCoord({ x: 0, y: 0 }, 'up')).toEqual({ x: 0, y: 1 });
    expect(nextCoord({ x: 0, y: 0 }, 'down')).toEqual({ x: 0, y: -1 });
  });
});

describe('groupPlacements', () => {
  it('同一 A 格合并朝向并按四向固定顺序排列', () => {
    const groups = groupPlacements([
      place(1, 0, 'up'),
      place(1, 0, 'right'),
      place(-1, 0, 'down'),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toEqual({ cell: { x: -1, y: 0 }, directions: ['down'] });
    expect(groups[1]).toEqual({ cell: { x: 1, y: 0 }, directions: ['right', 'up'] });
  });

  it('按坐标稳定排序，重复朝向只保留一次', () => {
    const groups = groupPlacements([place(0, 1, 'right'), place(0, -1, 'right'), place(0, 1, 'right')]);
    expect(groups.map((group) => group.cell)).toEqual([
      { x: 0, y: -1 },
      { x: 0, y: 1 },
    ]);
    expect(groups[1]?.directions).toEqual(['right']);
  });
});

describe('boundsOf 与 gridPosition', () => {
  it('外接矩形宽度与高度含首尾格', () => {
    const bounds = boundsOf([
      { x: 0, y: 0 },
      { x: 2, y: 1 },
      { x: -1, y: -2 },
    ]);
    expect(bounds).toEqual({ minX: -1, maxX: 2, minY: -2, maxY: 1, columns: 4, rows: 4 });
  });

  it('模型 y 最大者落在第一行，x 最小者落在第一列', () => {
    const bounds = boundsOf([
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ]);
    expect(gridPosition(bounds, { x: 0, y: 1 })).toEqual({ column: 0, row: 0 });
    expect(gridPosition(bounds, { x: 1, y: 0 })).toEqual({ column: 1, row: 1 });
  });
});
