import type { SchemaOf } from '@/api/http';
import { CharacterAvatar, CharacterName } from './CharacterAvatar';
import { MessageBubble } from './MessageBubble';
import type { MessageGroup } from '@/lib/groupMessages';
import { collectMentions, isOwnMessage, senderKey } from '@/lib/groupMessages';

type MessageView = SchemaOf<'MessageView'>;

export type { MessageGroup };

interface MessageGroupViewProps {
  readonly group: MessageGroup;
  readonly playerId: string;
  /** 发送主体标识到显示名的解析。 */
  readonly resolveName: (sender: MessageView['sender']) => string;
}

/**
 * 一组连续同发送者的消息。
 *
 * 头像只在组首显示一次，组内每条消息各成一块气泡；时间只在最后一条显示。
 * 自己发送的消息不显示头像，只保留同宽占位以维持对齐。
 */
export function MessageGroupView({ group, playerId, resolveName }: MessageGroupViewProps) {
  const first = group.messages[0];
  const own = first === undefined ? false : isOwnMessage(first, playerId);
  const name = resolveName(group.sender);
  const identity = senderKey(group.sender);

  return (
    <div className={`flex gap-2.5 ${own ? 'flex-row-reverse' : ''}`}>
      <div className="w-6 shrink-0 pt-0.5">
        {own ? null : <CharacterAvatar identity={identity} name={name} size="sm" />}
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
            resolveName={(actorId) => resolveName({ kind: 'character', actor_id: actorId })}
            isLast={index === group.messages.length - 1}
          />
        ))}
      </div>
    </div>
  );
}
