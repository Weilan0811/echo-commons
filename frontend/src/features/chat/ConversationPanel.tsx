import { useEffect, useMemo, useRef, useState } from 'react';
import { MessageCircle, MoreHorizontal, Users } from 'lucide-react';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { Composer, type ComposerTarget } from '@/components/Composer';
import { ConversationDetails } from '@/components/ConversationDetails';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { MessageGroupView, useSettledThrough } from '@/components/MessageGroup';
import { TurnStatusLane } from '@/components/TurnStatusLane';
import { useCommunity, useConversationMembers, type PublicDisplay } from '@/api/directory';
import {
  mergeMessages,
  useConversationDetail,
  useConversationHistory,
  useMarkRead,
  useMessagePoll,
  useSendMessage,
  useTurns,
  type ActorRef,
  type ConversationSummary,
  type PlayerMessageView,
} from '@/api/conversations';
import { deriveTurnStates } from '@/lib/deriveTurnStates';
import { groupMessages, senderKey } from '@/lib/groupMessages';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';
import { resolveCover } from '@/lib/coverPresets';

export function ConversationPanel({
  playerId,
  conversationId,
  mode = 'chat',
  visible = true,
  onUnreadChange,
  readOnlyMessage,
}: {
  playerId: string;
  conversationId: string;
  mode?: 'chat' | 'game';
  visible?: boolean;
  onUnreadChange?: (count: number) => void;
  readOnlyMessage?: string | undefined;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [replyTo, setReplyTo] = useState<PlayerMessageView | null>(null);
  const [documentVisible, setDocumentVisible] = useState(document.visibilityState === 'visible');
  const detail = useConversationDetail(playerId, conversationId);
  const active = detail.data;
  useEffect(() => {
    setReplyTo(null);
  }, [active?.self_membership_id]);
  const members = useConversationMembers(
    playerId,
    conversationId,
    active?.self_membership_status === 'current',
  );
  const memberList = useMemo(
    () => (active?.self_membership_status === 'current' ? (members.data?.items ?? []) : []),
    [members.data?.items, active?.self_membership_status],
  );
  const history = useConversationHistory(playerId, conversationId);
  const poll = useMessagePoll(
    playerId,
    conversationId,
    history.data?.pages[0]?.poll_cursor ?? null,
    true,
  );
  const turns = useTurns(playerId, conversationId, mode === 'chat');
  const markRead = useMarkRead(playerId);
  const send = useSendMessage(playerId, conversationId);
  const messages = useMemo(
    () =>
      mergeMessages(
        history.data?.pages.flatMap((page) => page.messages) ?? [],
        poll.data?.messages ?? [],
      ),
    [history.data, poll.data],
  );
  const peers = memberList.filter(
    (member) => member.actor.kind !== 'player' || member.actor.actor_id !== playerId,
  );
  const nameOfIdentity = (identity: string) =>
    memberList.find((member) => senderKey(member.actor) === identity)?.display_name ?? identity;
  const mentionTargets: ComposerTarget[] = memberList
    .filter((member) => member.actor.kind === 'character')
    .map((member) => ({
      identity: senderKey(member.actor),
      name: member.display_name,
      avatarUrl: resolveOfficialAvatar({
        avatarUrl: member.avatar_url,
        displayName: member.display_name,
      }),
      actor: member.actor as ActorRef,
    }));
  useEffect(() => {
    const update = () => setDocumentVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    onUnreadChange?.(active?.unread_count ?? 0);
  }, [active?.unread_count, onUnreadChange]);
  const lastVisible = messages.at(-1);
  const lastReadSequence = active?.last_read_sequence ?? 0;
  const mark = markRead.mutate;
  useEffect(() => {
    if (!visible || !documentVisible || !lastVisible || lastVisible.sequence <= lastReadSequence)
      return;
    mark({ conversationId, throughMessageId: lastVisible.message_id });
  }, [
    visible,
    documentVisible,
    conversationId,
    lastVisible?.message_id,
    lastVisible?.sequence,
    lastReadSequence,
    mark,
  ]);

  if (detail.error)
    return (
      <div className="p-4">
        <ErrorNotice error={detail.error} onRetry={() => void detail.refetch()} />
      </div>
    );
  if (!active) return <p className="p-5 text-sm text-content-muted">正在读取聊天…</p>;
  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      aria-label={mode === 'game' ? '局内聊天' : '当前会话'}
    >
      {mode === 'game' ? (
        <header className="game-chat-heading">
          <span className="game-eyebrow">
            <MessageCircle size={15} /> 桌边聊天
          </span>
          <span className="text-[11px] text-content-faint">
            {active.can_send ? '一边下棋，一边聊聊' : '聊天记录'}
          </span>
        </header>
      ) : (
        <ThreadHeader
          summary={active}
          peer={active.direct_peer ?? null}
          peers={peers}
          playerId={playerId}
          onMore={() => setDetailsOpen(true)}
        />
      )}
      {detailsOpen ? (
        <ConversationDetails
          summary={active}
          members={memberList}
          playerId={playerId}
          onClose={() => setDetailsOpen(false)}
        />
      ) : null}
      {history.error ? (
        <ErrorNotice error={history.error} onRetry={() => void history.refetch()} />
      ) : null}
      {poll.error ? <ErrorNotice error={poll.error} onRetry={() => void poll.refetch()} /> : null}
      <MessageScroller
        messages={messages}
        playerId={playerId}
        resolveName={nameOfIdentity}
        hasOlder={history.hasNextPage}
        isLoadingOlder={history.isFetching}
        onLoadOlder={() => {
          if (history.hasNextPage && !history.isFetching) void history.fetchNextPage();
        }}
        onReply={setReplyTo}
        canReply={active.can_send}
      />
      <div
        className={`shrink-0 border-t border-border-subtle ${mode === 'game' ? 'px-4 py-3' : 'px-5 py-3.5'}`}
      >
        {mode === 'chat' ? (
          <TurnStatusLane
            displays={deriveTurnStates(turns.data ?? [])}
            resolveName={(id) => nameOfIdentity(`character:${id}`)}
          />
        ) : null}
        {active.can_send ? (
          <Composer
            key={active.self_membership_id}
            characters={mentionTargets}
            replyTo={
              replyTo
                ? {
                    id: replyTo.message_id,
                    name: replyTo.sender_display.display_name,
                    text: replyTo.text,
                  }
                : null
            }
            onCancelReply={() => setReplyTo(null)}
            onSend={async (draft) => {
              await send.mutateAsync({
                text: draft.text,
                mentions: draft.mentions,
                replyToMessageId: draft.replyToMessageId,
              });
              setReplyTo(null);
            }}
          />
        ) : (
          <p className="text-xs leading-relaxed text-content-faint">
            {readOnlyMessage ??
              (active.status === 'archived'
                ? '活动已结束，消息保留在这里。'
                : '当前身份只能阅读聊天记录。')}
          </p>
        )}
      </div>
    </div>
  );
}

function ThreadHeader({
  summary,
  peer,
  peers,
  onMore,
  playerId,
}: {
  readonly summary: ConversationSummary;
  readonly peer: ConversationSummary['direct_peer'];
  readonly peers: readonly PublicDisplay[];
  readonly onMore: () => void;
  readonly playerId: string;
}) {
  const direct = peer ?? null;
  const title = summary.display_name;
  const isGroup = summary.kind === 'group';
  const community = useCommunity(playerId, summary.community_id);
  // 群聊没有独立头像，用所属社群的场景封面缩略，让会话与世界氛围一致。
  const cover = isGroup
    ? resolveCover(
        summary.community_id,
        title,
        community.data?.cover_kind,
        community.data?.cover_ref,
      )
    : null;

  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-border-subtle px-5 py-3">
      {direct !== null ? (
        <CharacterAvatar
          identity={actorIdentity(direct)}
          name={title}
          imageUrl={resolveOfficialAvatar({
            avatarUrl: direct.avatar_url,
            displayName: title,
          })}
          size="md"
          glow
        />
      ) : cover !== null ? (
        <img
          src={cover}
          alt=""
          className="size-11 shrink-0 rounded-xl object-cover shadow-[0_4px_14px_-6px_rgba(10,7,16,.8)]"
        />
      ) : (
        <span className="glass-soft flex size-11 shrink-0 items-center justify-center rounded-xl text-content-faint">
          <Users className="size-5" strokeWidth={1.6} />
        </span>
      )}

      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold">{title}</span>
          <span className="rounded-full bg-white/8 px-2 py-0.5 text-[10px] text-content-faint">
            {summary.kind === 'game' ? '局内聊天' : isGroup ? '群聊' : '私聊'}
          </span>
          {summary.self_membership_status === 'past' ? (
            <span className="rounded-full bg-white/8 px-2 py-0.5 text-[10px] text-content-faint">
              已离开
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 text-[11px] text-content-faint">
          {summary.unread_count > 0
            ? `${summary.unread_count} 条未读 · ${peers.length} 位伙伴`
            : `${peers.length} 位伙伴`}
        </p>
      </div>

      {isGroup ? (
        <div className="ml-auto flex items-center pr-1">
          <PeerAvatarStack peers={peers} />
        </div>
      ) : null}
      <button
        type="button"
        aria-label="会话详情"
        onClick={onMore}
        className="ml-auto rounded-full p-2 text-content-muted hover:bg-white/5"
      >
        <MoreHorizontal size={20} />
      </button>
    </header>
  );
}

/** 群成员头像堆叠。最多露五个，多出来的收成 +N，全部来自真实成员列表。 */
function PeerAvatarStack({ peers }: { readonly peers: readonly PublicDisplay[] }) {
  const shown = peers.slice(0, 5);
  const rest = peers.length - shown.length;
  if (shown.length === 0) return null;
  return (
    <div className="flex items-center">
      {shown.map((member) => (
        <span
          key={actorIdentity(member)}
          className="-ml-2 first:ml-0 rounded-full ring-2 ring-[color:var(--color-surface)]"
        >
          <CharacterAvatar
            identity={actorIdentity(member)}
            name={member.display_name}
            imageUrl={resolveOfficialAvatar({
              avatarUrl: member.avatar_url,
              displayName: member.display_name,
            })}
            size="sm"
          />
        </span>
      ))}
      {rest > 0 ? (
        <span className="glass-soft -ml-2 flex size-9 items-center justify-center rounded-full text-[11px] text-content-muted ring-2 ring-[color:var(--color-surface)]">
          +{rest}
        </span>
      ) : null}
    </div>
  );
}

/** 参与者身份键。与 groupMessages.senderKey 使用同一形状，配色才能一致。 */
function actorIdentity(display: PublicDisplay): string {
  return display.actor.kind === 'system'
    ? `system:${display.actor.source_id}`
    : `${display.actor.kind}:${display.actor.actor_id}`;
}

function MessageScroller({
  messages,
  playerId,
  resolveName,
  hasOlder,
  isLoadingOlder,
  onLoadOlder,
  onReply,
  canReply,
}: {
  readonly messages: readonly PlayerMessageView[];
  readonly playerId: string;
  readonly resolveName: (identity: string) => string;
  readonly hasOlder: boolean;
  readonly isLoadingOlder: boolean;
  readonly onLoadOlder: () => void;
  readonly onReply: (message: PlayerMessageView) => void;
  readonly canReply: boolean;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  // 首次渲染时已存在的消息不算新增，历史消息不会逐条重播入场动画。
  const settled = useSettledThrough(messages[messages.length - 1]?.sequence);

  // 会话默认停在最新消息。已经在往回翻阅时不抢滚动位置，否则每 4 秒的
  // 增量轮询都会把使用者拉回底部。
  const pinnedToBottom = useRef(true);
  useEffect(() => {
    const element = viewport.current;
    if (element === null || !pinnedToBottom.current) return;
    element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <EmptyState
        title="还没有消息"
        description={canReply ? '发送一条消息开始对话。' : '本次参与期间没有可见消息。'}
      />
    );
  }
  const groups = groupMessages(messages);
  return (
    <div
      ref={viewport}
      onScroll={(event) => {
        const element = event.currentTarget;
        pinnedToBottom.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 120;
      }}
      className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
    >
      {/* 消息流铺满会话区：气泡靠左右两边对齐，长文气泡在 MessageGroup 内限宽，
          宽屏下不再在两侧留出大片居中留白。 */}
      <div className="flex w-full flex-col gap-3">
        {hasOlder ? (
          <button
            type="button"
            onClick={onLoadOlder}
            disabled={isLoadingOlder}
            className="glass-soft mx-auto mb-1 rounded-full px-3 py-1 text-[11px] text-content-faint transition-colors hover:text-content disabled:opacity-50"
          >
            {isLoadingOlder ? '正在读取…' : '读取更早的消息'}
          </button>
        ) : null}
        {groups.map((group, index) => (
          <div key={`${senderKey(group.sender)}-${index}`} className="animate-rise-in">
            <MessageGroupView
              group={group}
              playerId={playerId}
              resolveMentionName={resolveName}
              settledThrough={settled}
              onReply={canReply ? onReply : undefined}
              resolveReply={(id) => messages.find((item) => item.message_id === id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
