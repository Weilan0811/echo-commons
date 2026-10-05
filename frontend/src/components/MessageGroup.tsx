import { CharacterAvatar, CharacterName } from './CharacterAvatar';
import { MessageBubble } from './MessageBubble';
import type { MessageGroup } from '@/lib/groupMessages';
import { collectMentions, isOwnMessage, senderKey } from '@/lib/groupMessages';

export type { MessageGroup };

interface MessageGroupViewProps {
  readonly group: MessageGroup;
  readonly playerId: string;
  /**
   * 提及身份到显示名的解析。
   *
   * 提及在正文中以标识出现，需要换成名称；名称取自会话成员列表，
   * 消息本身只保证携带发送者与被提及者的标识。
   */
  readonly resolveMentionName: (identity: string) => string;
}

/**
 * 一组连续同发送者的消息。
 *
 * 发送者名称与头像直接取自消息携带的公开身份，不在界面维护名称映射。
 * 头像只在组首显示一次，组内每条消息各成一块气泡；时间只在最后一条显示。
 * 自己发送的消息不显示头像，只保留同宽占位以维持对齐。
 */
export function MessageGroupView({ group, playerId, resolveMentionName }: MessageGroupViewProps) {
  const first = group.messages[0];
  if (first === undefined) return null;
  const own = isOwnMessage(first, playerId);
  const display = first.sender_display;
  const name = display.display_name;
  const identity = senderKey(first.sender);

  return (
    <div className={`flex gap-2.5 ${own ? 'flex-row-reverse' : ''}`}>
      <div className="w-6 shrink-0 pt-0.5">
        {own ? null : (
          <CharacterAvatar
            identity={identity}
            name={name}
            imageUrl={display.avatar_url}
            size="sm"
          />
        )}
      </div>

      <div className={`flex min-w-0 max-w-[min(30rem,78%)] flex-col gap-1.5 ${own ? 'items-end' : 'items-start'}`}>
        {!own ? (
          <div className="px-1">
            <CharacterName identity={identity} className="text-xs font-medium">
              {name}
            </CharacterName>
          </div>
        ) : null}

        {group.messages.map((message, index) => (
          <MessageBubble
            key={message.message_id}
            message={message}
            playerId={playerId}
            mentioned={collectMentions(message)}
            resolveName={resolveMentionName}
            isLast={index === group.messages.length - 1}
          />
        ))}
      </div>
    </div>
  );
}
