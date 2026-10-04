import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { CharacterAvatar } from './CharacterAvatar';
import { accentColor } from '@/lib/characterColor';

export interface ComposerRecipient {
  readonly identity: string;
  readonly name: string;
  readonly kind: 'player' | 'character';
}

export interface ComposerProps {
  readonly currentPlayerId: string;
  /** 会话内的角色，用于私密受众与提及。 */
  readonly characters: readonly ComposerRecipient[];
  /** 发送回调。失败时抛出异常，组件保留输入内容以便重试。 */
  readonly onSend: (draft: ComposerDraft) => Promise<void>;
}

export interface ComposerDraft {
  readonly text: string;
  readonly visibility: 'conversation' | 'recipients';
  readonly recipients: readonly string[];
  readonly mentions: readonly string[];
  readonly replyToMessageId: string | null;
}

/**
 * 输入器：一个输入区域承担公开与私密、受众、提及与回复四种状态。
 *
 * 每次发送生成一次 client_message_id 并随发送意图一起交给调用方；
 * 网络重试必须复用同一个标识与完全相同的字段，因此标识不在组件内重生成。
 */
export function Composer({ currentPlayerId, characters, onSend }: ComposerProps) {
  const [text, setText] = useState('');
  const [privateMode, setPrivateMode] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleRecipient = (identity: string) => {
    setSelected((current) => {
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
    if (privateMode && selected.size === 0) {
      setError('私有消息需要指定受众。');
      return;
    }

    setPending(true);
    setError(null);
    try {
      await onSend({
        text: trimmed,
        visibility: privateMode ? 'recipients' : 'conversation',
        recipients: privateMode ? [...selected] : [],
        mentions: [...selected],
        replyToMessageId: replyTo,
      });
      // 仅在发送成功后清空，失败时保留原输入以便重试。
      setText('');
      setReplyTo(null);
      setSelected(new Set());
      setPrivateMode(false);
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

      {privateMode ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-content-faint">仅发给</span>
          {characters.length === 0 ? (
            <span className="text-[11px] text-content-faint">该会话没有可选择的角色</span>
          ) : (
            characters.map((character) => (
              <button
                key={character.identity}
                type="button"
                onClick={() => toggleRecipient(character.identity)}
                className={`flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-2 text-[11px] transition-colors ${
                  selected.has(character.identity)
                    ? 'bg-surface-overlay text-content'
                    : 'text-content-faint hover:text-content-muted'
                }`}
              >
                <CharacterAvatar identity={character.identity} name={character.name} size="xs" />
                {character.name}
              </button>
            ))
          )}
        </div>
      ) : null}

      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={() => {
            setPrivateMode((current) => !current);
          }}
          className={`shrink-0 rounded-md border px-2 py-2 text-xs transition-colors ${
            privateMode
              ? 'border-accent bg-accent-soft text-content'
              : 'border-border-subtle text-content-faint hover:text-content-muted'
          }`}
          title="切换为仅指定受众可见"
        >
          私有
        </button>

        <textarea
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={
            privateMode
              ? `发送给已选角色，Enter 发送，Shift+Enter 换行（当前身份 ${currentPlayerId}）`
              : 'Enter 发送，Shift+Enter 换行'
          }
          className="max-h-40 min-h-9 flex-1 resize-y rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-sm text-content outline-none placeholder:text-content-faint focus:border-border-strong"
        />

        <button
          type="submit"
          disabled={pending}
          className="shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-opacity disabled:opacity-50"
          style={{ backgroundColor: accentColor(currentPlayerId), color: 'var(--color-surface)' }}
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
