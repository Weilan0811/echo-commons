import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { SendHorizonal } from 'lucide-react';
import type { ActorRef } from '@/api/directory';
import { CharacterAvatar } from './CharacterAvatar';

export interface ComposerTarget {
  /** 稳定身份键，用于配色与选中状态。 */
  readonly identity: string;
  readonly name: string;
  /** 官方随包头像或服务端地址；为空时提及胶囊用装饰模板。 */
  readonly avatarUrl?: string | null;
  /** 发送时提交的参与者引用，由服务端契约给出，不在界面拼装。 */
  readonly actor: ActorRef;
}

export interface ComposerProps {
  /** 会话内的角色，用于提及。 */
  readonly characters: readonly ComposerTarget[];
  /** 发送回调。失败时抛出异常，组件保留输入内容以便重试。 */
  readonly onSend: (draft: ComposerDraft) => Promise<void>;
}

export interface ComposerDraft {
  readonly text: string;
  /** 被提及的角色。提及用于调度优先，不改变可见范围。 */
  readonly mentions: readonly ActorRef[];
  readonly replyToMessageId: string | null;
}

/**
 * 输入器：一个输入区域承担提及与回复两种状态。
 *
 * 消息对会话成员一律可见，界面不提供指定受众的入口：契约已移除可见范围字段，
 * 需要私下沟通时另开私聊，而不是在同一个会话里制造只有部分人看得到的记录。
 *
 * 接口层为发送内容分配 client_message_id，失败后的相同内容继续使用原编号。
 */
export function Composer({ characters, onSend }: ComposerProps) {
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
        // 选中状态按稳定身份记录，提交时换回契约要求的参与者引用。
        mentions: characters
          .filter((character) => mentioned.has(character.identity))
          .map((character) => character.actor),
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
        <div className="glass-soft flex items-center justify-between rounded-xl border-l-2 border-accent px-3 py-1.5 text-xs text-content-muted">
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
              className={`flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-2.5 text-[11px] transition-colors ${
                mentioned.has(character.identity)
                  ? 'bg-accent-soft text-content'
                  : 'text-content-faint hover:text-content-muted'
              }`}
            >
              <CharacterAvatar
                identity={character.identity}
                name={character.name}
                imageUrl={character.avatarUrl ?? null}
                size="xs"
              />
              {character.name}
            </button>
          ))}
        </div>
      ) : null}

      {/*
       * 输入区是一条柔和的悬浮玻璃：圆角拉满、焦点时暖金描边与一圈很淡的
       * 外发光，提示它是对话的一部分而不是后台表单。field-sizing 让它随内容
       * 增高，最小两行，不出现内部滚动条。
       */}
      <div className="glass-soft flex items-end gap-2 rounded-[22px] p-2 pl-4 transition-[border-color,box-shadow] focus-within:border-accent/50 focus-within:shadow-[0_0_0_3px_color-mix(in_oklch,var(--color-accent)_14%,transparent),0_10px_30px_-12px_rgba(10,7,16,.7)]">
        <textarea
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="说点什么…"
          className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed text-content outline-none placeholder:text-content-faint"
        />

        <button
          type="submit"
          disabled={pending || text.trim() === ''}
          className="flex shrink-0 items-center gap-1.5 rounded-full bg-accent px-4 py-2.5 text-[13px] font-semibold text-accent-ink transition-[filter,transform,opacity] hover:brightness-110 active:scale-95 disabled:opacity-40"
        >
          <SendHorizonal className="size-4" strokeWidth={2} />
          {pending ? '发送中' : '发送'}
        </button>
      </div>

      <p className="px-1 text-[10px] text-content-faint">
        Enter 发送，Shift+Enter 换行
      </p>

      {error !== null ? (
        <p role="alert" className="px-1 text-xs text-danger">
          {error}
        </p>
      ) : null}
    </form>
  );
}
