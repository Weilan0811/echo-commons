import { describe, expect, it } from 'vitest';
import { isUsableClientMessageId, newClientMessageId } from './clientMessageId';

describe('newClientMessageId', () => {
  it('返回非空字符串', () => {
    expect(newClientMessageId().length).toBeGreaterThan(0);
  });

  it('连续两次生成不同标识', () => {
    // 契约要求每次新输入生成独立标识；重复发送必须复用原标识，
    // 因此生成函数不能返回相同值。
    const ids = new Set(Array.from({ length: 50 }, () => newClientMessageId()));
    expect(ids.size).toBe(50);
  });

  it('标识不含空白，可直接作为请求字段', () => {
    expect(isUsableClientMessageId(newClientMessageId())).toBe(true);
  });
});

describe('isUsableClientMessageId', () => {
  it('拒绝空字符串与纯空白', () => {
    expect(isUsableClientMessageId('')).toBe(false);
    expect(isUsableClientMessageId('   ')).toBe(false);
  });

  it('接受非空标识', () => {
    expect(isUsableClientMessageId('abc')).toBe(true);
  });
});
