import { describe, expect, it } from 'vitest';
import type { SchemaOf } from '@/api/http';
import { collectMentions, groupMessages, isOwnMessage, senderKey } from './groupMessages';

type MessageView = SchemaOf<'PlayerMessageView'>;

function message(overrides: Partial<MessageView>): MessageView {
  return {
    message_id: 'm1',
    conversation_id: 'c1',
    sequence: 1,
    sender: { kind: 'character', actor_id: 'preview-jin' },
    text: '文本',
    mentions: [],
    reply_to_message_id: null,
    source_turn_id: null,
    created_at_utc: '2026-10-04T00:00:00Z',
    ...overrides,
  } as MessageView;
}

describe('senderKey', () => {
  it('玩家与角色带 actor_id', () => {
    expect(senderKey({ kind: 'player', actor_id: 'preview-me' })).toBe('player:preview-me');
    expect(senderKey({ kind: 'character', actor_id: 'preview-jin' })).toBe('character:preview-jin');
  });

  it('系统消息带 source_id，不会与同名角色混淆', () => {
    expect(senderKey({ kind: 'system', source_id: 'sys-1' })).toBe('system:sys-1');
  });
});

describe('groupMessages', () => {
  it('空输入返回空数组', () => {
    expect(groupMessages([])).toEqual([]);
  });

  it('连续同发送者合并为一块', () => {
    const groups = groupMessages([
      message({ message_id: 'm1', sequence: 1 }),
      message({ message_id: 'm2', sequence: 2 }),
      message({ message_id: 'm3', sequence: 3 }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.messages).toHaveLength(3);
  });

  it('发送者变化时切断分组', () => {
    const groups = groupMessages([
      message({ message_id: 'm1', sequence: 1 }),
      message({
        message_id: 'm2',
        sequence: 2,
        sender: { kind: 'character', actor_id: 'preview-an' },
      }),
    ]);
    expect(groups).toHaveLength(2);
  });

  it('同类不同实例不合并', () => {
    const groups = groupMessages([
      message({ message_id: 'm1', sequence: 1, sender: { kind: 'character', actor_id: 'a' } }),
      message({ message_id: 'm2', sequence: 2, sender: { kind: 'character', actor_id: 'b' } }),
    ]);
    expect(groups).toHaveLength(2);
  });

  it('系统消息独立成组，不与角色消息合并', () => {
    const groups = groupMessages([
      message({ message_id: 'm1', sequence: 1 }),
      message({
        message_id: 'm2',
        sequence: 2,
        sender: { kind: 'system', source_id: 'sys-1' },
      }),
    ]);
    expect(groups).toHaveLength(2);
  });

  it('分组不改变消息本身，也不合并不同序号', () => {
    const input = [
      message({ message_id: 'm1', sequence: 3 }),
      message({ message_id: 'm2', sequence: 7 }),
    ];
    const groups = groupMessages(input);
    expect(groups[0]?.messages.map((item) => item.message_id)).toEqual(['m1', 'm2']);
    expect(groups[0]?.messages.map((item) => item.sequence)).toEqual([3, 7]);
  });

  it('保留输入顺序，不重新排序', () => {
    const groups = groupMessages([
      message({ message_id: 'm1', sequence: 5, sender: { kind: 'player', actor_id: 'me' } }),
      message({
        message_id: 'm2',
        sequence: 9,
        sender: { kind: 'character', actor_id: 'preview-jin' },
      }),
      message({ message_id: 'm3', sequence: 12, sender: { kind: 'player', actor_id: 'me' } }),
    ]);
    expect(groups).toHaveLength(3);
    expect(senderKey(groups[2]?.sender ?? { kind: 'player', actor_id: '' })).toBe('player:me');
  });
});

describe('isOwnMessage', () => {
  it('当前玩家的消息判定为自己发送', () => {
    const own = message({ sender: { kind: 'player', actor_id: 'preview-me' } });
    expect(isOwnMessage(own, 'preview-me')).toBe(true);
  });

  it('其他玩家的消息不算自己发送', () => {
    const other = message({ sender: { kind: 'player', actor_id: 'preview-other' } });
    expect(isOwnMessage(other, 'preview-me')).toBe(false);
  });

  it('角色消息不算自己发送，即使标识与玩家相同', () => {
    const character = message({ sender: { kind: 'character', actor_id: 'preview-me' } });
    expect(isOwnMessage(character, 'preview-me')).toBe(false);
  });

  it('系统消息不算自己发送', () => {
    const system = message({ sender: { kind: 'system', source_id: 'sys-1' } });
    expect(isOwnMessage(system, 'preview-me')).toBe(false);
  });
});

describe('collectMentions', () => {
  it('无提及时返回空集合', () => {
    expect(collectMentions(message({ mentions: [] })).size).toBe(0);
  });

  it('收集被提及的身份', () => {
    const withMentions = message({
      mentions: [
        { kind: 'character', actor_id: 'preview-jin' },
        { kind: 'character', actor_id: 'preview-an' },
      ],
    });
    expect([...collectMentions(withMentions)].sort()).toEqual(['preview-an', 'preview-jin']);
  });
});
