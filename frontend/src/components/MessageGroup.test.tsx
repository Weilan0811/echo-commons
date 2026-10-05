import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { SchemaOf } from '@/api/http';
import { groupMessages } from '@/lib/groupMessages';
import { MessageGroupView } from './MessageGroup';

type MessageView = SchemaOf<'PlayerMessageView'>;

const NAMES: Record<string, string> = {
  'preview-jin': '小槿',
  'preview-an': '阿澈',
  'preview-bo': '阿澈',
  'preview-me': '我',
};

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

function renderGroup(messages: readonly MessageView[]) {
  const groups = groupMessages(messages);
  const group = groups[0];
  if (group === undefined) throw new Error('需要至少一条消息');
  return render(
    <MessageGroupView
      group={group}
      playerId="preview-me"
      resolveName={(sender) => (sender.kind === 'system' ? '系统' : NAMES[sender.actor_id] ?? sender.actor_id)}
    />,
  );
}

describe('MessageGroupView', () => {
  it('显示角色名与消息正文', () => {
    renderGroup([
      message({ text: '今晚吃什么？', sender: { kind: 'character', actor_id: 'preview-jin' } }),
    ]);
    expect(screen.getByText('小槿')).toBeInTheDocument();
    expect(screen.getByText('今晚吃什么？')).toBeInTheDocument();
  });

  it('自己发送的消息不显示角色名', () => {
    renderGroup([message({ sender: { kind: 'player', actor_id: 'preview-me' }, text: '我说一句' })]);
    expect(screen.queryByText('我')).not.toBeInTheDocument();
    expect(screen.getByText('我说一句')).toBeInTheDocument();
  });

  it('未超过阈值的消息保持单个气泡', () => {
    const short = '今晚吃什么？';
    const { container } = renderGroup([message({ text: short })]);
    expect(container.querySelectorAll('p')).toHaveLength(1);
  });

  it('超过阈值的消息拆成多个气泡且内容完整', () => {
    // 契约说明一次角色回应保存为一条完整消息，界面可拆成多个气泡，
    // 但不逐个发送，因此渲染层拆分后正文必须完整。
    const long =
      '第一句内容比较长，需要一点时间来说明。第二句承接前面继续补充说明。第三句再补充一个不同的观点。第四句给出最后的结论。';
    const { container } = renderGroup([message({ text: long })]);
    expect(container.querySelectorAll('p').length).toBeGreaterThan(1);
    for (const clause of ['第一句内容比较长', '第二句承接前面', '第三句再补充', '第四句给出']) {
      expect(container.textContent).toContain(clause);
    }
  });

  it('提及的角色名被高亮', () => {
    renderGroup([
      message({
        text: '@preview-an 你觉得呢',
        mentions: [{ kind: 'character', actor_id: 'preview-an' }],
      }),
    ]);
    expect(screen.getByText('@阿澈').className).toContain('font-medium');
  });

  it('未提及的角色名不高亮', () => {
    renderGroup([
      message({
        text: '@preview-bo 谁在听',
        mentions: [{ kind: 'character', actor_id: 'preview-an' }],
      }),
    ]);
    expect(screen.getByText('@阿澈').className).toContain('text-content-faint');
  });
});
