import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { CharacterAvatar } from './CharacterAvatar';
import { ErrorNotice } from './ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useCommunityMembers,
  useCommunityCharacters,
  useCreateConversation,
  type ActorRef,
  type PublicDisplay,
} from '@/api/directory';
import { canCharacterChat, characterStatusText } from '@/lib/characterReadiness';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';

/**
 * 新建会话。
 *
 * 参与者来自服务端返回的社群成员，界面不维护可选名单。
 * 发起人始终是参与者，因此不在名单里单列。
 *
 * 私聊在契约里固定为「一名玩家加一名角色」：发起人是那名玩家，对方只能
 * 是角色。允许玩家对玩家的私聊会被服务端拒绝，界面不提供该选项。
 */
/** 初始预选。角色档案的「开始聊天」用它直达与该角色的私聊。 */
export interface NewConversationInitial {
  readonly kind: 'group' | 'direct';
  readonly characterId?: string;
}

export function NewConversationDialog({
  onClose,
  initial,
}: {
  readonly onClose: () => void;
  readonly initial?: NewConversationInitial | undefined;
}) {
  const { subject } = useCurrentSubject();
  const navigate = useNavigate();
  const playerId = subject.playerId;
  const communityId = subject.communityId;

  const members = useCommunityMembers(playerId, communityId);
  const characters = useCommunityCharacters(playerId, communityId);
  const create = useCreateConversation();
  const [kind, setKind] = useState<'group' | 'direct'>(initial?.kind ?? 'group');
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  const peers = useMemo(() => {
    const all = (members.data?.items ?? []).filter(
      (member) => member.actor.kind !== 'player' || member.actor.actor_id !== playerId,
    );
    return kind === 'direct' ? all.filter((member) => member.actor.kind === 'character') : all;
  }, [members.data?.items, playerId, kind]);

  const statusOf = (peer: PublicDisplay): string | null => {
    if (peer.actor.kind !== 'character') return null;
    const characterId = peer.actor.actor_id;
    const character = characters.data?.find((item) => item.character_id === characterId);
    if (character === undefined) return characters.isError ? '状态读取失败' : '正在读取状态';
    return canCharacterChat(character) ? null : characterStatusText(character);
  };

  // 预选角色在成员与状态加载完成后生效；不可聊天的角色不会被预选。
  const initialCharacterId = initial?.characterId;
  useEffect(() => {
    if (kind !== 'direct' || initialCharacterId === undefined) return;
    const target = peers.find(
      (peer) =>
        peer.actor.kind === 'character' &&
        peer.actor.actor_id === initialCharacterId &&
        statusOf(peer) === null,
    );
    if (target === undefined) return;
    const key = actorKey(target);
    setSelected((current) => (current.has(key) ? current : new Set([key])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, initialCharacterId, peers, characters.data]);

  const chosen = peers.filter((peer) => selected.has(actorKey(peer)) && statusOf(peer) === null);

  const toggle = (peer: PublicDisplay) => {
    if (statusOf(peer) !== null) return;
    const key = actorKey(peer);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
        return next;
      }
      // 私聊只有一个对方，改选即替换。
      if (kind === 'direct') return new Set([key]);
      next.add(key);
      return next;
    });
  };

  const canSubmit = communityId !== null && chosen.length > 0 && (kind === 'group' || chosen.length === 1);

  const submit = async () => {
    if (!canSubmit || communityId === null) return;
    const actors: ActorRef[] = [
      { kind: 'player', actor_id: playerId },
      ...chosen.map((peer) => peer.actor as ActorRef),
    ];
    try {
      const created = await create.mutateAsync({ communityId, playerId, kind, actors });
      onClose();
      void navigate(`/app/chat/${created.conversation_id}`);
    } catch {
      // 失败信息由下方 ErrorNotice 呈现，对话框保持打开以便调整选择。
    }
  };

  return (
    <div className="animate-fade-in fixed inset-0 z-10 flex items-center justify-center bg-black/55 p-6 backdrop-blur-[2px]">
      <div className="glass-panel animate-rise-in flex max-h-[80vh] w-full max-w-md flex-col rounded-card">
        <header className="flex shrink-0 items-center justify-between border-b border-border-subtle px-5 py-4">
          <h2 className="text-[15px] font-semibold">新建会话</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-2 py-0.5 text-xs text-content-faint transition-colors hover:bg-white/8 hover:text-content"
          >
            关闭
          </button>
        </header>

        <div className="flex shrink-0 gap-1.5 px-4 py-3">
          {(['group', 'direct'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => {
                setKind(option);
                if (option === 'direct') {
                  const first = chosen[0];
                  setSelected(first === undefined ? new Set() : new Set(actorKey(first)));
                }
              }}
              className={`rounded-full px-3.5 py-1.5 text-xs transition-colors ${
                kind === option
                  ? 'bg-accent-soft text-accent'
                  : 'text-content-faint hover:text-content-muted'
              }`}
            >
              {option === 'group' ? '群聊' : '私聊'}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {members.isError ? (
            <div className="p-2">
              <ErrorNotice error={members.error} />
            </div>
          ) : null}
          {characters.isError ? <ErrorNotice error={characters.error} /> : null}

          {peers.length === 0 && !members.isPending ? (
            <p className="px-2 py-3 text-xs text-content-faint">
              社群里还没有其他成员。先创建角色，或让其他玩家加入这个社群。
            </p>
          ) : null}

          {peers.map((peer) => {
            const key = actorKey(peer);
            const unavailable = statusOf(peer);
            const active = selected.has(key) && unavailable === null;
            return (
              <button
                key={key}
                type="button"
                disabled={unavailable !== null}
                onClick={() => {
                  toggle(peer);
                }}
                className={`mx-2 flex w-[calc(100%-1rem)] items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors disabled:opacity-50 ${
                  active ? 'bg-accent-soft' : 'hover:bg-white/5'
                }`}
              >
                <CharacterAvatar
                  identity={key}
                  name={peer.display_name}
                  imageUrl={resolveOfficialAvatar({
                    avatarUrl: peer.avatar_url,
                    displayName: peer.display_name,
                  })}
                  size="sm"
                />
                <span className="min-w-0 flex-1 truncate text-xs">{peer.display_name}</span>
                <span className="shrink-0 text-[10px] text-content-faint">
                  {unavailable ?? (peer.actor.kind === 'character' ? '角色' : '玩家')}
                </span>
              </button>
            );
          })}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-2 border-t border-border-subtle px-5 py-3.5">
          <span className="text-[11px] text-content-faint">
            {kind === 'direct' ? '选择一位对方开始私聊' : `已选 ${chosen.length} 位`}
          </span>
          <button
            type="button"
            onClick={() => {
              void submit();
            }}
            disabled={!canSubmit || create.isPending}
            className="rounded-full bg-accent px-5 py-2 text-[13px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
          >
            {create.isPending ? '创建中' : '创建'}
          </button>
        </footer>

        {create.isError ? (
          <div className="px-4 pb-3">
            <ErrorNotice error={create.error} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** 成员身份键。与 groupMessages.senderKey 形状一致，配色才能与消息一致。 */
function actorKey(display: PublicDisplay): string {
  return display.actor.kind === 'system'
    ? `system:${display.actor.source_id}`
    : `${display.actor.kind}:${display.actor.actor_id}`;
}
