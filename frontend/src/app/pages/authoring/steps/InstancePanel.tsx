import { useState } from 'react';
import { Link } from 'react-router';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import {
  useCommunityCharacters,
  useCreateCharacter,
  useRetryCharacterMemory,
  type CharacterView,
} from '@/api/directory';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { canCharacterChat, characterPreparationError, characterStatusText } from '@/lib/characterReadiness';

/**
 * 固定之后让人物入住当前社群。
 *
 * 运行模式创建后不可切换，因此在选择时直接写明；材料 stored_only 时要与
 * 「已就绪」区分开——原文已存但记忆准备未完成前不能聊天。
 */
export function InstancePanel({
  playerId,
  blueprintId,
  displayName,
  avatarUrl,
  hasMaterials,
  materialNotice,
}: {
  readonly playerId: string;
  readonly blueprintId: string;
  readonly displayName: string;
  readonly avatarUrl: string | null;
  readonly hasMaterials: boolean;
  readonly materialNotice: string;
}) {
  const { subject } = useCurrentSubject();
  const communityId = subject.communityId;
  const create = useCreateCharacter();
  const retryMemory = useRetryCharacterMemory(playerId, communityId);
  const [mode, setMode] = useState<'simple' | 'full'>('simple');
  const [created, setCreated] = useState<CharacterView | null>(null);

  // 已在当前社群建过实例时也允许从列表看到状态，不阻断重复读取。
  const characters = useCommunityCharacters(playerId, communityId);
  const existing =
    created
    ?? (characters.data?.find((item) => item.blueprint_id === blueprintId) ?? null);

  if (communityId === null) {
    return (
      <div className="rounded-card border border-border-subtle bg-surface-overlay/30 p-5">
        <h3 className="text-[14px] font-semibold">让 TA 入住社群</h3>
        <p className="mt-2 text-[12px] leading-relaxed text-content-faint">
          人物已经固定，但还没有选择社群。先选择或创建一个社群，再让 TA 入住。
        </p>
        <Link
          to="/app/communities"
          className="mt-3 inline-block rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] text-accent hover:bg-accent/20"
        >
          去选择社群
        </Link>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border-subtle bg-surface-overlay/30 p-5">
      <h3 className="text-[14px] font-semibold">让 TA 入住当前社群</h3>
      <p className="mt-1.5 text-[11px] text-content-faint">
        只有社群成员能创建实例；入住后同社群其他成员都可以与 TA 交流。
      </p>

      <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
        <ModeCard
          active={mode === 'simple'}
          title="简单模式"
          caption="原文分块检索即可聊天，准备更快。"
          recommended
          onClick={() => setMode('simple')}
        />
        <ModeCard
          active={mode === 'full'}
          title="完整模式"
          caption="先把材料整理成长期记忆，准备更久，也可能需要模型额度。"
          onClick={() => setMode('full')}
        />
      </div>
      <p className="mt-2 text-[10px] text-warn">运行模式在创建后不可切换。</p>

      {hasMaterials ? (
        <p className="mt-3 rounded-lg border border-border-subtle bg-surface-sunken/60 px-3 py-2 text-[11px] leading-relaxed text-content-faint">
          {materialNotice}
          准备完成前 TA 还不能加入会话。
        </p>
      ) : null}

      {create.isError ? (
        <div className="mt-3"><ErrorNotice error={create.error} /></div>
      ) : null}

      {existing === null ? (
        <button
          type="button"
          disabled={create.isPending}
          onClick={() => {
            void create
              .mutateAsync({ communityId, playerId, blueprintId, memoryMode: mode })
              .then((character) => setCreated(character))
              .catch(() => undefined);
          }}
          className="mt-4 rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110 disabled:opacity-40"
        >
          {create.isPending ? '入住中…' : `以${mode === 'simple' ? '简单' : '完整'}模式入住社群`}
        </button>
      ) : (
        <CreatedCharacterCard
          character={existing}
          avatarUrl={existing.avatar_url ?? avatarUrl}
          retrying={retryMemory.isPending}
          onRetry={() => retryMemory.mutate(existing.character_id)}
        />
      )}
    </div>
  );
}

function ModeCard({
  active,
  title,
  caption,
  recommended,
  onClick,
}: {
  readonly active: boolean;
  readonly title: string;
  readonly caption: string;
  readonly recommended?: boolean;
  readonly onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border p-3 text-left transition-colors ${
        active
          ? 'border-accent bg-accent-soft/60 ring-1 ring-accent/40'
          : 'border-border-subtle bg-surface-sunken/50 hover:border-accent/40'
      }`}
    >
      <span className="flex items-center gap-2 text-[13px] font-semibold">
        {title}
        {recommended ? (
          <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-medium text-accent">默认</span>
        ) : null}
      </span>
      <span className="mt-1 block text-[11px] leading-relaxed text-content-faint">{caption}</span>
    </button>
  );
}

function CreatedCharacterCard({
  character,
  avatarUrl,
  retrying,
  onRetry,
}: {
  readonly character: CharacterView;
  readonly avatarUrl: string | null;
  readonly retrying: boolean;
  readonly onRetry: () => void;
}) {
  const ready = canCharacterChat(character);
  return (
    <div className="mt-4 rounded-lg border border-border-subtle bg-surface-sunken/60 p-3.5">
      <div className="flex items-center gap-3">
        <CharacterAvatar
          identity={`character:${character.character_id}`}
          name={character.display_name}
          imageUrl={avatarUrl}
          size="md"
          glow
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold">{character.display_name}</p>
          <p className={'text-[11px] ' + (ready ? 'text-ok' : 'text-warn')}>{characterStatusText(character)}</p>
        </div>
        {ready ? (
          <Link
            to="/app/chat"
            className="rounded-lg border border-accent/50 bg-accent-soft px-3 py-1.5 text-[12px] text-accent hover:bg-accent/20"
          >
            去聊天
          </Link>
        ) : null}
      </div>
      {character.memory_status === 'failed' ? (
        <div className="mt-2.5 border-t border-border-subtle pt-2.5">
          <p className="break-words text-[11px] text-danger">{characterPreparationError(character)}</p>
          <button
            type="button"
            disabled={retrying}
            onClick={onRetry}
            className="mt-1.5 rounded border border-danger/40 px-2.5 py-1 text-[11px] text-danger hover:bg-danger/10 disabled:opacity-50"
          >
            {retrying ? '正在提交…' : '重新准备'}
          </button>
        </div>
      ) : null}
    </div>
  );
}
