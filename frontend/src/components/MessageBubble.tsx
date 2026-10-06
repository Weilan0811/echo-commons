import type { ReactNode } from 'react';
import type { SchemaOf } from '@/api/http';
import { accentColor, splitForBubbles } from '@/lib/characterColor';
import { bubbleDelays } from '@/lib/bubbleDelay';

type MessageView = SchemaOf<'PlayerMessageView'>;

interface MessageBubbleProps {
  readonly message: MessageView;
  /** 发送者稳定标识，用于派生气泡底色。 */
  readonly identity: string;
  /** 当前玩家，用于区分左右气泡。 */
  readonly playerId: string;
  /** 被提及的角色标识，用于高亮。 */
  readonly mentioned: ReadonlySet<string>;
  /** 提及身份到显示名的解析。正文里以标识出现，界面显示名称。 */
  readonly resolveName: (identity: string) => string;
  /** 是否为组内最后一条，决定时间是否显示。 */
  readonly isLast: boolean;
  /**
   * 入场时已存在的最大序号。
   *
   * 只有比它更新的消息才逐个错开入场：会话里已有的历史消息一次全部出现，
   * 逐条重播会把刚打开的会话看成角色正在慢慢打字。
   */
  readonly settledThrough: number;
}

/**
 * 单条消息的气泡组。
 *
 * 契约说明一次角色回应保存为一条完整消息，界面可以按显示需要拆成多个气泡，
 * 但不向后端逐个发送气泡，因此拆分只发生在渲染层。角色消息里的换行表示真实
 * 的说话停顿，拆成独立气泡并依次入场；玩家消息保留输入框里的换行，不拆。
 *
 * 别人的气泡用角色派生色掺进面板色，而不是直接用角色色：派生色的色相是均匀
 * 分布的，落在底色色相附近时直接使用会整块融进背景，掺色后无论什么色相都
 * 保有明度差。自己的气泡用琥珀实心，在一屏别人的低饱和气泡里一眼可辨。
 */
export function MessageBubble({
  message,
  identity,
  playerId,
  mentioned,
  resolveName,
  isLast,
  settledThrough,
}: MessageBubbleProps) {
  const own = message.sender.kind === 'player' && message.sender.actor_id === playerId;
  const bubbles = splitForBubbles(message.text, 48, !own);
  // 只有新进入的消息才逐段错开，历史消息一次出现。
  const staggered = message.sequence > settledThrough;
  const delays = staggered
    ? bubbleDelays(bubbles.map((bubble) => bubble.length))
    : bubbles.map(() => 0);

  return (
    <div className={`flex flex-col gap-0.5 ${own ? 'items-end' : 'items-start'}`}>
      {bubbles.map((bubble, index) => (
        <div
          key={`${message.message_id}-${index}`}
          className={staggered ? 'animate-bubble-in' : undefined}
          style={staggered ? { animationDelay: `${delays[index] ?? 0}ms` } : undefined}
        >
          <div
            className={`w-fit max-w-full rounded-bubble px-3.5 py-2 ${
              own ? 'rounded-br-[6px]' : 'rounded-bl-[6px]'
            }`}
            style={
              own
                ? { backgroundColor: 'var(--color-accent)', color: 'var(--color-accent-ink)' }
                : {
                    backgroundColor: `color-mix(in oklch, ${accentColor(identity)} 13%, var(--color-surface-raised))`,
                  }
            }
          >
            <p className="text-sm leading-[1.7]">{renderText(bubble, mentioned, resolveName, own)}</p>
          </div>
        </div>
      ))}
      {isLast ? (
        <span className="tabular mt-1 px-1 text-[10px] text-content-faint">
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
  own: boolean,
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
        className={isMentioned ? 'font-semibold' : 'opacity-70'}
        // 自己的气泡底色已经足够亮，角色色压上去不可读，改用加深与加粗区分。
        style={isMentioned && !own ? { color: accentColor(identity) } : undefined}
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
