import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { CharacterAvatar } from './CharacterAvatar';

export interface ComposerTarget {
  readonly identity: string;
  readonly name: string;
}

export interface ComposerProps {
  readonly currentPlayerId: string;
  /** 会话内的角色，用于提及。 */
  readonly characters: readonly ComposerTarget[];
  /** 发送回调。失败时抛出异常，组件保留输入内容以便重试。 */
  readonly onSend: (draft: ComposerDraft) => Promise<void>;
}

export interface ComposerDraft {
  readonly text: string;
  /** 被提及的角色。提及用于调度优先，不改变可见范围。 */
  readonly mentions: readonly string[];
  readonly replyToMessageId: string | null;
}

/**
 * 输入器：一个输入区域承担提及与回复两种状态。
 *
 * 消息对会话成员一律可见，界面不提供指定受众的入口：契约已移除可见范围字段，
 * 需要私下沟通时另开私聊，而不是在同一个会话里制造只有部分人看得到的记录。
 *
 * 每次发送生成一次 client_message_id 并随发送意图一起交给调用方；
 * 网络重试必须复用同一个标识与完全相同的字段，因此标识不在组件内重生成。
 */
export function Composer({ currentPlayerId, characters, onSend }: ComposerProps) {
  const [text, setText] = useState('');
  const [mentioned, setMentioned] = useState<ReadonlySet<string>>(new Set());
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleMention = (identity: string) => {
    setMentioned((current) => {
      const next = new Set(current);
      if (next.has(identity)) next.delete(identity);
      else next.add(identity);
      return next;
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    const trimmed = text.trim();
    if (trimmed === '') return;

    setPending(true);
    setError(null);
    try {
      await onSend({
        text: trimmed,
        mentions: [...mentioned],
        replyToMessageId: replyTo,
      });
      // 仅在发送成功后清空，失败时保留原输入以便重试。
      setText('');
      setReplyTo(null);
      setMentioned(new Set());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '发送失败，请重试。');
    } finally {
      setPending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // 契约要求一条输入对应一条消息；换行用 Shift+Enter，发送用 Enter。
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit(event);
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-2">
      {replyTo !== null ? (
        <div className="flex items-center justify-between rounded border-l-2 border-accent bg-surface-raised px-2.5 py-1.5 text-xs text-content-muted">
          <span>正在回复一条消息</span>
          <button
            type="button"
            onClick={() => {
              setReplyTo(null);
            }}
            className="text-content-faint hover:text-content"
          >
            取消
          </button>
        </div>
      ) : null}

      {characters.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-content-faint">提及</span>
          {characters.map((character) => (
            <button
              key={character.identity}
              type="button"
              onClick={() => toggleMention(character.identity)}
              className={`flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-2 text-[11px] transition-colors ${
                mentioned.has(character.identity)
                  ? 'bg-surface-overlay text-content'
                  : 'text-content-faint hover:text-content-muted'
              }`}
            >
              <CharacterAvatar identity={character.identity} name={character.name} size="xs" />
              {character.name}
            </button>
          ))}
        </div>
      ) : null}

      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={`Enter 发送，Shift+Enter 换行（当前身份 ${currentPlayerId}）`}
          className="max-h-40 min-h-9 flex-1 resize-y rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-sm text-content outline-none placeholder:text-content-faint focus:border-border-strong"
        />

        <button
          type="submit"
          disabled={pending}
          className="shrink-0 rounded-md px-3 py-2 text-sm font-medium text-surface transition-opacity disabled:opacity-50"
          style={{ backgroundColor: 'var(--color-accent)' }}
        >
          {pending ? '发送中' : '发送'}
        </button>
      </div>

      {error !== null ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </form>
  );
}
