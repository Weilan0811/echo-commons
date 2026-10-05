import type { ReactNode } from 'react';
import type { SchemaOf } from '@/api/http';
import { accentColor, splitForBubbles } from '@/lib/characterColor';

type MessageView = SchemaOf<'MessageView'>;

interface MessageBubbleProps {
  readonly message: MessageView;
  /** 当前玩家，用于区分左右气泡。 */
  readonly playerId: string;
  /** 被提及的角色标识，用于高亮。 */
  readonly mentioned: ReadonlySet<string>;
  /** 标识到显示名的解析。提及在正文中以标识出现，界面显示名称。 */
  readonly resolveName: (identity: string) => string;
  /** 是否为组内最后一条，决定时间是否显示。 */
  readonly isLast: boolean;
}

/**
 * 单个气泡。
 *
 * 契约说明一次角色回应保存为一条完整消息，界面可以按显示需要拆成多个气泡，
 * 但不向后端逐个发送气泡，因此拆分只发生在渲染层。
 */
export function MessageBubble({
  message,
  playerId,
  mentioned,
  resolveName,
  isLast,
}: MessageBubbleProps) {
  const own = message.sender.kind === 'player' && message.sender.actor_id === playerId;
  const bubbles = splitForBubbles(message.text);

  return (
    <div className={`flex flex-col ${own ? 'items-end' : 'items-start'}`}>
      <div
        className={`flex w-fit flex-col gap-1 rounded-2xl px-3.5 py-2 ${
          own ? 'rounded-br-md bg-accent-soft text-content' : 'rounded-bl-md bg-surface-raised'
        }`}
      >
        {bubbles.map((bubble, index) => (
          <p key={`${message.message_id}-${index}`} className="text-sm leading-relaxed">
            {renderText(bubble, mentioned, resolveName)}
          </p>
        ))}
      </div>
      {isLast ? (
        <span className="mt-1 px-1 text-[10px] text-content-faint">
          {formatTime(message.created_at_utc)}
        </span>
      ) : null}
    </div>
  );
}

/**
 * 渲染正文并高亮提及。
 *
 * 提及用于调度与高亮，不改变可见范围。
 */
function renderText(
  text: string,
  mentioned: ReadonlySet<string>,
  resolveName: (identity: string) => string,
): ReactNode {
  if (mentioned.size === 0) return text;

  // 带捕获组的 split 会保留分隔符，因此提及标记本身也能被渲染。
  const tokens = text.split(/(@[^\s@]+)/g);

  return tokens.map((token, index) => {
    if (!token.startsWith('@')) return token;
    const identity = token.slice(1);
    const isMentioned = mentioned.has(identity);
    const label = resolveName(identity);
    return (
      <span
        key={`${index}-${identity}`}
        className={isMentioned ? 'font-medium' : 'text-content-faint'}
        style={isMentioned ? { color: accentColor(identity) } : undefined}
      >
        @{label}
      </span>
    );
  });
}

/** 消息时间。契约返回带时区 ISO 8601，这里只取时分。 */
function formatTime(isoUtc: string): string {
  const parsed = new Date(isoUtc);
  if (Number.isNaN(parsed.getTime())) return '';
  const hours = `${parsed.getHours()}`.padStart(2, '0');
  const minutes = `${parsed.getMinutes()}`.padStart(2, '0');
  return `${hours}:${minutes}`;
}
