import { describe, expect, it } from 'vitest';
import {
  boundsOf,
  displayBounds,
  groupPlacements,
  gridPosition,
  nextCoord,
  type PlaceAction,
} from './layout';

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
    const groups = groupPlacements([place(1, 0, 'up'), place(1, 0, 'right'), place(-1, 0, 'down')]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toEqual({ cell: { x: -1, y: 0 }, directions: ['down'] });
    expect(groups[1]).toEqual({
      cell: { x: 1, y: 0 },
      directions: ['right', 'up'],
    });
  });

  it('按坐标稳定排序，重复朝向只保留一次', () => {
    const groups = groupPlacements([
      place(0, 1, 'right'),
      place(0, -1, 'right'),
      place(0, 1, 'right'),
    ]);
    expect(groups.map((group) => group.cell)).toEqual([
      { x: 0, y: -1 },
      { x: 0, y: 1 },
    ]);
    expect(groups[1]?.directions).toEqual(['right']);
  });
});

describe('boundsOf 与 gridPosition', () => {
  it('开局以城堡为中心补足展示范围', () => {
    expect(displayBounds([{ x: 0, y: 0 }])).toEqual({
      minX: -2,
      maxX: 2,
      minY: -2,
      maxY: 2,
      columns: 5,
      rows: 5,
    });
  });

  it('候选落点超过五格范围时全部保留，包含负坐标和 B 格', () => {
    const points = [
      { x: -4, y: -1 },
      { x: 3, y: 2 },
    ];
    const bounds = displayBounds(points);
    expect(bounds.columns).toBe(8);
    expect(bounds.rows).toBe(8);
    for (const point of points) {
      const position = gridPosition(bounds, point);
      expect(position.column).toBeGreaterThanOrEqual(0);
      expect(position.column).toBeLessThan(bounds.columns);
      expect(position.row).toBeGreaterThanOrEqual(0);
      expect(position.row).toBeLessThan(bounds.rows);
    }
  });
  it('外接矩形宽度与高度含首尾格', () => {
    const bounds = boundsOf([
      { x: 0, y: 0 },
      { x: 2, y: 1 },
      { x: -1, y: -2 },
    ]);
    expect(bounds).toEqual({
      minX: -1,
      maxX: 2,
      minY: -2,
      maxY: 1,
      columns: 4,
      rows: 4,
    });
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
