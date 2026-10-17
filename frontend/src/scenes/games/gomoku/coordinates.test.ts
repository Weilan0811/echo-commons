import { describe, expect, it } from 'vitest';
import { coordinateLabel, intersectionAt } from './coordinates';

describe('五子棋交点输入', () => {
  it('将棋盘中心和四角转换为正式坐标', () => {
    expect(intersectionAt(48, 48)).toEqual({ x: 0, y: 0 });
    expect(intersectionAt(552, 48)).toEqual({ x: 14, y: 0 });
    expect(intersectionAt(48, 552)).toEqual({ x: 0, y: 14 });
    expect(intersectionAt(552, 552)).toEqual({ x: 14, y: 14 });
    expect(intersectionAt(300, 300)).toEqual({ x: 7, y: 7 });
  });
  it('选择最近交点，棋盘外不产生落子', () => {
    expect(intersectionAt(311, 292)).toEqual({ x: 7, y: 7 });
    for (const [x, y] of [
      [0, 300],
      [600, 300],
      [300, 0],
      [300, 600],
    ]) {
      expect(intersectionAt(x!, y!)).toBeNull();
    }
  });
  it('坐标名称与棋盘标尺一致', () => {
    expect(coordinateLabel({ x: 0, y: 0 })).toBe('A1');
    expect(coordinateLabel({ x: 7, y: 7 })).toBe('H8');
    expect(coordinateLabel({ x: 14, y: 14 })).toBe('O15');
  });
});
