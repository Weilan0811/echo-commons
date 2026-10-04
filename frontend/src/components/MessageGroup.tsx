import type { SchemaOf } from '@/api/http';
import { CharacterAvatar, CharacterName } from './CharacterAvatar';
import { MessageBubble } from './MessageBubble';
import type { MessageGroup } from '@/lib/groupMessages';
import { collectMentions, isOwnMessage, senderKey } from '@/lib/groupMessages';
import { accentColor } from '@/lib/characterColor';

type MessageView = SchemaOf<'MessageView'>;

export type { MessageGroup };

interface MessageGroupViewProps {
  readonly group: MessageGroup;
  readonly playerId: string;
  /** 显示名解析：角色标识与玩家标识映射到名称。 */
  readonly resolveName: (sender: MessageView['sender']) => string;
}

/**
 * 一组连续同发送者的消息。
 *
 * 头像只在组首显示一次，组内每条消息各成一块气泡；时间只在最后一条显示。
 */
export function MessageGroupView({ group, playerId, resolveName }: MessageGroupViewProps) {
  const own = isOwnMessage(group.messages[0] ?? ({ sender: group.sender } as MessageView), playerId);
  const name = resolveName(group.sender);
  const identity = senderKey(group.sender);
  const isPrivate = group.visibility === 'recipients';

  return (
    <div className={`flex gap-2.5 ${own ? 'flex-row-reverse' : ''}`}>
      <div className="shrink-0 pt-0.5">
        <CharacterAvatar identity={identity} name={name} size="sm" />
      </div>

      <div className={`flex min-w-0 flex-col gap-1.5 ${own ? 'items-end' : 'items-start'}`}>
        {!own ? (
          <div className="flex items-center gap-1.5 px-1">
            <CharacterName identity={identity} className="text-xs font-medium">
              {name}
            </CharacterName>
            {isPrivate ? <PrivateBadge /> : null}
          </div>
        ) : null}

        {group.messages.map((message, index) => (
          <MessageBubble
            key={message.message_id}
            message={message}
            playerId={playerId}
            mentioned={collectMentions(message)}
            isLast={index === group.messages.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

/** 私有消息标记。与契约的 recipients 可见性对应。 */
function PrivateBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint"
      title="仅指定受众可见"
    >
      <svg viewBox="0 0 12 12" className="size-2.5" aria-hidden="true" fill="none" strokeWidth={1.6}>
        <rect x="2.2" y="5" width="7.6" height="5" rx="1.2" stroke="currentColor" />
        <path d="M4 5V3.8a2 2 0 0 1 4 0V5" stroke="currentColor" strokeLinecap="round" />
      </svg>
      私有
    </span>
  );
}

/** 分组发送者的强调色，供列表等位置复用。 */
export function groupAccent(group: MessageGroup): string {
  return accentColor(senderKey(group.sender));
}
