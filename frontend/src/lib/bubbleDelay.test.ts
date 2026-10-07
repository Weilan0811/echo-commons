import { describe, expect, it } from 'vitest';
import { bubbleDelays } from './bubbleDelay';

describe('bubbleDelays', () => {
  it('单段没有延迟', () => {
    expect(bubbleDelays([20])).toEqual([0]);
  });

  it('空输入返回空结果', () => {
    expect(bubbleDelays([])).toEqual([]);
  });

  it('首段立即出现，后续依次错开', () => {
    const delays = bubbleDelays([10, 10, 10]);
    expect(delays[0]).toBe(0);
    expect(delays[1]).toBeGreaterThan(0);
    expect(delays[2]).toBeGreaterThan(delays[1] ?? 0);
  });

  it('段落越长，下一段的等待越久', () => {
    const short = bubbleDelays([5, 5]);
    const long = bubbleDelays([40, 40]);
    expect(long[1]).toBeGreaterThan(short[1] ?? 0);
  });

  it('长段落的贡献有上限，不会把后面推得太远', () => {
    const capped = bubbleDelays([1000, 10]);
    const veryLong = bubbleDelays([100000, 10]);
    // 两者都应停在上限对应的总时长上。
    expect(veryLong[1]).toBe(capped[1]);
  });

  it('延迟总长随段落数增长但保持轻量', () => {
    const delays = bubbleDelays(Array.from({ length: 5 }, () => 30));
    const last = delays[delays.length - 1] ?? 0;
    expect(last).toBeGreaterThan(0);
    // 五段在两秒内发完：再慢就不像聊天了。
    expect(last).toBeLessThan(2000);
  });
});