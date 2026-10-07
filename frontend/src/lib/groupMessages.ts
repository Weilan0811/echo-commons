import type { SchemaOf } from '@/api/http';

type MessageView = SchemaOf<'PlayerMessageView'>;
type Sender = MessageView['sender'];

/**
 * 发送主体的稳定键。
 *
 * 契约中 sender 是联合类型：玩家与角色带 actor_id，系统消息带 source_id。
 * 分组、列表键与配色的输入统一走这里，避免各处重复判断变体。
 */
export function senderKey(sender: Sender): string {
  return sender.kind === 'system'
    ? `system:${sender.source_id}`
    : `${sender.kind}:${sender.actor_id}`;
}

/**
 * 连续同发送者的消息合并为一块，用于在界面上作为一组呈现。
 *
 * 契约说明一次角色回应保存为一条完整消息，界面可以按显示需要拆成多个气泡。
 * 因此分组只合并展示单元，不改变消息本身，也不改变发送行为。
 */
export interface MessageGroup {
  readonly sender: Sender;
  readonly messages: readonly MessageView[];
}

/**
 * 按发送者把消息序列合并为分组。
 *
 * 输入需按序号升序。空输入返回空数组。
 */
export function groupMessages(messages: readonly MessageView[]): MessageGroup[] {
  const groups: Array<{ sender: Sender; messages: MessageView[] }> = [];

  for (const message of messages) {
    const last = groups[groups.length - 1];
    if (last !== undefined && senderKey(last.sender) === senderKey(message.sender)) {
      last.messages.push(message);
      continue;
    }
    groups.push({ sender: message.sender, messages: [message] });
  }

  return groups;
}

/** 判断某条消息是否由当前玩家发送，用于区分左右气泡。 */
export function isOwnMessage(message: MessageView, playerId: string): boolean {
  return message.sender.kind === 'player' && message.sender.actor_id === playerId;
}

/**
 * 收集消息中被提及的角色身份。
 *
 * 提及用于调度与高亮，不改变可见范围：消息对会话成员一律可见。
 */
export function collectMentions(message: MessageView): ReadonlySet<string> {
  return new Set(message.mentions.map((mention) => mention.actor_id));
}
