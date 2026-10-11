import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { CharacterAvatar, CharacterName } from './CharacterAvatar';
import { MessageBubble } from './MessageBubble';
import type { MessageGroup } from '@/lib/groupMessages';
import { collectMentions, isOwnMessage, senderKey } from '@/lib/groupMessages';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';

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
  /**
   * 入场时已存在的最大序号。
   *
   * 只有比它更新的消息才逐个错开入场。刚打开会话时全部历史一次出现，
   * 否则会把已经发生过的对话看成角色正在慢慢打字。
   */
  readonly settledThrough: number;
}

/**
 * 一组连续同发送者的消息。
 *
 * 发送者名称与头像直接取自消息携带的公开身份，不在界面维护名称映射。
 * 头像只在组首显示一次，组内每条消息各成一块气泡；时间只在最后一条显示。
 * 自己发送的消息不显示头像，只保留同宽占位以维持对齐。
 */
export function MessageGroupView({
  group,
  playerId,
  resolveMentionName,
  settledThrough,
}: MessageGroupViewProps) {
  const first = group.messages[0];
  if (first === undefined) return null;
  const own = isOwnMessage(first, playerId);
  const display = first.sender_display;
  const name = display.display_name;
  const identity = senderKey(first.sender);

  return (
    <div className={`flex gap-2.5 ${own ? 'flex-row-reverse' : ''}`}>
      <div className="w-9 shrink-0 pt-0.5">
        {own ? null : (
          <CharacterAvatar
            identity={identity}
            name={name}
            imageUrl={resolveOfficialAvatar({
              avatarUrl: display.avatar_url,
              displayName: name,
            })}
            size="sm"
            glow
          />
        )}
      </div>

      <div
        className={`flex min-w-0 max-w-[min(46rem,calc(100%-2.75rem))] flex-col gap-1.5 ${
          own ? 'items-end' : 'items-start'
        }`}
      >
        {!own ? (
          <div className="flex items-baseline gap-2 px-1">
            <CharacterName identity={identity} className="text-xs font-semibold">
              {name}
            </CharacterName>
          </div>
        ) : null}

        {group.messages.map((message, index) => (
          <MessageBubble
            key={message.message_id}
            message={message}
            identity={identity}
            playerId={playerId}
            mentioned={collectMentions(message)}
            resolveName={resolveMentionName}
            isLast={index === group.messages.length - 1}
            settledThrough={settledThrough}
          />
        ))}
      </div>
    </div>
  );
}

/**
/**
 * 记下首次拿到消息时的最大序号。
 *
 * 只有比它更新的消息才算新进入，因此历史消息一次出现，不会在每次轮询时被
 * 重新当成新消息逐段播放。时机是「首次有消息」而不是「首次渲染」：会话打开
 * 时消息还没到，那时记录会得到 0，随后到达的历史消息就会被误当成新增。
 *
 * 赋值在渲染期完成且是幂等的，严格模式下重复执行结果一致。
 */
export function useSettledThrough(sequence: number | undefined): number {
  const settled = useRef<number | null>(null);
  if (settled.current === null && sequence !== undefined) settled.current = sequence;
  return settled.current ?? 0;
}
