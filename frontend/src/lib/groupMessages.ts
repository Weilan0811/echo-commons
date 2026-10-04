import type { SchemaOf } from '@/api/http';

type MessageView = SchemaOf<'MessageView'>;
type Sender = MessageView['sender'];
type Visibility = MessageView['visibility'];

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
  readonly visibility: Visibility;
  readonly messages: readonly MessageView[];
}

/**
 * 按发送者与可见性把消息序列合并为分组。
 *
 * 可见性变化会切断分组：公开消息与私有消息即使来自同一主体，也不应合并在
 * 同一组内，否则私有消息的不同底色会失去意义。
 *
 * 输入需按序号升序。空输入返回空数组。
 */
export function groupMessages(messages: readonly MessageView[]): MessageGroup[] {
  const groups: Array<{
    sender: Sender;
    visibility: Visibility;
    messages: MessageView[];
  }> = [];

  for (const message of messages) {
    const last = groups[groups.length - 1];
    if (
      last !== undefined &&
      senderKey(last.sender) === senderKey(message.sender) &&
      last.visibility === message.visibility
    ) {
      last.messages.push(message);
      continue;
    }
    groups.push({
      sender: message.sender,
      visibility: message.visibility,
      messages: [message],
    });
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
 * 提及只用于高亮显示，实际可见范围由 visibility 与 recipients 决定，
 * 因此这里不参与任何可见性判断。
 */
export function collectMentions(message: MessageView): ReadonlySet<string> {
  return new Set(message.mentions.map((mention) => mention.actor_id));
}

/** 消息是否为指定受众可见。 */
export function isPrivateMessage(message: MessageView): boolean {
  return message.visibility === 'recipients';
}
