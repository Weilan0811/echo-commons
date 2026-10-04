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
  const isPrivate = group.visibility === 'recipients';

  return (
    <div className={`flex gap-2.5 ${own ? 'flex-row-reverse' : ''}`}>
      <div className="w-6 shrink-0 pt-0.5">
        {own ? null : <CharacterAvatar identity={identity} name={name} size="sm" />}
      </div>

      {/* 百分比最大宽度放在这里而不是气泡上：本容器的可用宽度由父级行决定，是确定值；
       若把百分比交给宽度由内容决定的气泡，会形成循环依赖，浏览器会把它算成很小的值。
       气泡自身只用 w-fit 跟随内容宽度。 */}
      <div className={`flex min-w-0 max-w-[min(30rem,78%)] flex-col gap-1.5 ${own ? 'items-end' : 'items-start'}`}>
        {/* 私有标记与发送者无关：自己发出的私有消息同样需要标明可见范围。 */}
        {!own || isPrivate ? (
          <div className={`flex items-center gap-1.5 px-1 ${own ? '' : ''}`}>
            {own ? null : (
              <CharacterName identity={identity} className="text-xs font-medium">
                {name}
              </CharacterName>
            )}
            {isPrivate ? <PrivateBadge /> : null}
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
