import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { Composer, type ComposerTarget } from '@/components/Composer';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { MessageGroupView } from '@/components/MessageGroup';
import { NewConversationDialog } from '@/components/NewConversationDialog';
import { TurnStatusLane } from '@/components/TurnStatusLane';
import { Shell } from '@/components/Shell';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { deriveTurnStates } from '@/lib/deriveTurnStates';
import { groupMessages, senderKey } from '@/lib/groupMessages';
import { newClientMessageId } from '@/lib/clientMessageId';
import { useConversationMembers, type PublicDisplay } from '@/api/directory';
import {
  fetchOlderPage,
  useConversationHistory,
  useConversationList,
  useMarkRead,
  useMessagePoll,
  useSendMessage,
  useTurns,
  type ActorRef,
  type ConversationSummary,
  type PlayerMessageView,
} from '@/api/conversations';

/**
 * 聊天页：左侧会话列表常驻，右侧展开选中的会话。
 *
 * 会话摘要、消息、轮次与阅读位置全部来自后端。前端不维护成员名单、
 * 显示名映射或阅读位置，这些都由服务端按读取身份给出。
 */
export function ChatPage() {
  const { conversationId = '' } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const { subject } = useCurrentSubject();
  const playerId = subject.playerId;
  const [creating, setCreating] = useState(false);

  const list = useConversationList(playerId, subject.communityId);
  const active = list.data?.items.find((item) => item.conversation_id === conversationId);

  const members = useConversationMembers(playerId, conversationId);
  const memberList = useMemo(() => members.data?.items ?? [], [members.data?.items]);

  const history = useConversationHistory(playerId, conversationId);
  const [olderPages, setOlderPages] = useState<PlayerMessageView[]>([]);
  const pollCursor = history.data?.poll_cursor ?? null;
  const poll = useMessagePoll(playerId, conversationId, pollCursor, conversationId !== '');
  const turns = useTurns(playerId, conversationId, conversationId !== '');
  const markRead = useMarkRead(playerId);
  const send = useSendMessage(playerId, conversationId);

  // 切换会话时清空向前翻出的历史，避免混入其他会话。
  useEffect(() => {
    setOlderPages([]);
  }, [conversationId]);

  const messages = useMemo(() => {
    const base = history.data?.messages ?? [];
    const fresh = poll.data?.messages ?? [];
    return [...olderPages, ...base, ...fresh];
  }, [olderPages, history.data?.messages, poll.data?.messages]);

  // 会话成员是会话的子集：群聊标题、提及候选与角色名都从这里取。
  // 契约没有单独的群聊名称，标题由除自己外的成员名派生。
  const peers = useMemo(
    () => memberList.filter((member) => member.actor.kind !== 'player' || member.actor.actor_id !== playerId),
    [memberList, playerId],
  );

  const nameOfIdentity = useMemo(() => {
    const table = new Map<string, PublicDisplay>();
    for (const member of memberList) {
      if (member.actor.kind === 'system') continue;
      table.set(`${member.actor.kind}:${member.actor.actor_id}`, member);
    }
    return (identity: string): string => table.get(identity)?.display_name ?? identity;
  }, [memberList]);

  const mentionTargets = useMemo<ComposerTarget[]>(
    () =>
      memberList
        .filter((member) => member.actor.kind === 'character')
        .map((member) => ({
          identity: `character:${member.actor.kind === 'system' ? '' : member.actor.actor_id}`,
          name: member.display_name,
          actor: member.actor as ActorRef,
        })),
    [memberList],
  );

  // 展示新消息后推进阅读位置。契约说明读取本身不标记已读，因此需要显式提交。
  // 阅读位置只前进，未读数以会话摘要的 last_read_sequence 为准。
  const lastVisible = messages[messages.length - 1];
  const lastReadSequence = active?.last_read_sequence ?? 0;
  useEffect(() => {
    if (conversationId === '') return;
    if (lastVisible === undefined) return;
    if (lastVisible.sequence <= lastReadSequence) return;
    if (document.visibilityState !== 'visible') return;
    markRead.mutate({ conversationId, throughMessageId: lastVisible.message_id });
  }, [conversationId, lastVisible?.message_id, lastVisible?.sequence, lastReadSequence]);

  const listColumn = (
    <ConversationList
      summaries={list.data?.items ?? []}
      activeId={conversationId === '' ? null : conversationId}
      isLoading={list.isPending}
      error={list.error}
      onSelect={(id) => {
        void navigate(`/app/chat/${id}`);
      }}
      onCreate={() => {
        setCreating(true);
      }}
      canCreate={subject.communityId !== null}
    />
  );

  if (playerId === '') {
    return (
      <Shell section="chat" list={listColumn}>
        <EmptyState title="先登记身份" description="身份决定能看到哪些会话，从顶栏的「身份」进入。" />
      </Shell>
    );
  }

  return (
    <Shell section="chat" list={listColumn}>
      {creating ? (
        <NewConversationDialog
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}

      {active === undefined ? (
        <EmptyState
          title="选择一个会话"
          description={
            subject.communityId === null
              ? '先在顶栏的「社群」里选一个。'
              : '左侧列表按最后可见消息时间排序。'
          }
        />
      ) : (
        <>
          <ThreadHeader
            summary={active}
            peer={active.direct_peer ?? null}
            peers={peers}
          />
          <MessageScroller
            key={conversationId}
            messages={messages}
            playerId={playerId}
            resolveName={nameOfIdentity}
            hasOlder={history.data?.has_older ?? false}
            isLoadingOlder={history.isFetching}
            onLoadOlder={() => {
              const cursor = history.data?.older_cursor;
              if (cursor === null || cursor === undefined) return;
              void fetchOlderPage(playerId, conversationId, cursor).then((page) => {
                setOlderPages((current) => [...page.messages, ...current]);
              });
            }}
          />
          <div className="shrink-0 border-t border-border-subtle px-4 py-3">
            <TurnStatusLane
              displays={deriveTurnStates(turns.data ?? [])}
              resolveName={(id) => nameOfIdentity(`character:${id}`)}
            />
            {active.can_send ? (
              <div className="mt-2">
                <Composer
                  characters={mentionTargets}
                  onSend={async (draft) => {
                    await send.mutateAsync({
                      playerId,
                      clientMessageId: newClientMessageId(),
                      text: draft.text,
                      mentions: draft.mentions,
                      replyToMessageId: draft.replyToMessageId,
                    });
                  }}
                />
              </div>
            ) : (
              <p className="mt-2 text-xs text-content-faint">当前身份不能在该会话发言。</p>
            )}
            {send.isError ? <ErrorNotice error={send.error} /> : null}
          </div>
        </>
      )}
    </Shell>
  );
}

function ThreadHeader({
  summary,
  peer,
  peers,
}: {
  readonly summary: ConversationSummary;
  readonly peer: ConversationSummary['direct_peer'];
  readonly peers: readonly PublicDisplay[];
}) {
  const direct = peer ?? null;
  const title =
    direct !== null
      ? direct.display_name
      : conversationTitle(peers);
  const avatarIdentity =
    direct !== null
      ? actorIdentity(direct)
      : `group:${summary.conversation_id}`;

  return (
    <header className="flex shrink-0 items-center gap-2.5 border-b border-border-subtle px-4 py-3">
      <CharacterAvatar
        identity={avatarIdentity}
        name={title}
        imageUrl={direct?.avatar_url ?? null}
        size="sm"
      />
      <span className="text-sm font-medium">{title}</span>
      <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
        {summary.kind === 'group' ? '群聊' : '私聊'}
      </span>
      {summary.self_membership_status === 'past' ? (
        <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
          已离开
        </span>
      ) : null}
      <span className="ml-auto text-[11px] text-content-faint">
        {summary.unread_count > 0 ? `${summary.unread_count} 条未读` : `${peers.length} 位成员`}
      </span>
    </header>
  );
}

/**
 * 群聊标题。
 *
 * 契约里的会话没有名称字段，摘要只有标识。这里用除自己外的成员名派生标题，
 * 属于展示层拼装：成员名单本身来自服务端，创建会话后由服务端维护。
 */
function conversationTitle(peers: readonly PublicDisplay[]): string {
  if (peers.length === 0) return '只有你';
  const names = peers.map((peer) => peer.display_name);
  if (names.length <= 3) return names.join('、');
  return `${names.slice(0, 3).join('、')} 等 ${names.length} 人`;
}

/** 参与者身份键。与 groupMessages.senderKey 使用同一形状，配色才能一致。 */
function actorIdentity(display: PublicDisplay): string {
  return display.actor.kind === 'system'
    ? `system:${display.actor.source_id}`
    : `${display.actor.kind}:${display.actor.actor_id}`;
}

function ConversationList({
  summaries,
  activeId,
  isLoading,
  error,
  onSelect,
  onCreate,
  canCreate,
}: {
  readonly summaries: readonly ConversationSummary[];
  readonly activeId: string | null;
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly onSelect: (conversationId: string) => void;
  readonly onCreate: () => void;
  readonly canCreate: boolean;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between px-3 py-2">
        <span className="text-[11px] uppercase tracking-wide text-content-faint">会话</span>
        {canCreate ? (
          <button
            type="button"
            onClick={onCreate}
            title="新建会话"
            className="rounded border border-border-subtle px-1.5 py-0.5 text-[11px] text-content-muted hover:border-border-strong hover:text-content"
          >
            新建
          </button>
        ) : null}
      </div>

      {error !== null && error !== undefined ? (
        <div className="px-3 pb-3">
          <ErrorNotice error={error} />
        </div>
      ) : null}

      {isLoading ? (
        <p className="px-3 pb-3 text-xs text-content-faint">正在读取会话…</p>
      ) : null}

      {!isLoading && error == null && summaries.length === 0 ? (
        <p className="px-3 pb-3 text-xs text-content-faint">还没有会话。</p>
      ) : null}

      {error == null && summaries.length > 0 ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ListSection title="群聊" items={summaries} activeId={activeId} onSelect={onSelect} />
          <ListSection title="私聊" items={summaries} activeId={activeId} onSelect={onSelect} />
        </div>
      ) : null}
    </div>
  );
}

function ListSection({
  title,
  items,
  activeId,
  onSelect,
}: {
  readonly title: string;
  readonly items: readonly ConversationSummary[];
  readonly activeId: string | null;
  readonly onSelect: (conversationId: string) => void;
}) {
  const kind = title === '群聊' ? 'group' : 'direct';
  const section = items.filter((item) => item.kind === kind);
  if (section.length === 0) return null;

  return (
    <div className="flex flex-col">
      <p className="px-3 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-widest text-content-faint">
        {title}
      </p>
      {section.map((item) => {
        const peer = item.direct_peer ?? null;
        const name = peer === null ? item.conversation_id : peer.display_name;
        const identity = peer === null ? `group:${item.conversation_id}` : actorIdentity(peer);
        const unread = item.unread_count;
        return (
          <button
            key={item.conversation_id}
            type="button"
            onClick={() => {
              onSelect(item.conversation_id);
            }}
            className={`relative flex w-full items-center gap-2.5 py-2 pl-3.5 pr-3 text-left transition-colors ${
              item.conversation_id === activeId
                ? 'bg-surface-raised'
                : 'hover:bg-surface-raised/60'
            }`}
          >
            {/*
             * 未读用左侧竖条而不是圆点。深色界面上圆点容易被头像吞掉，
             * 竖条贴着列表边缘，未读与已读的分界一眼可见。
             */}
            <span
              className={`absolute inset-y-1.5 left-0 w-0.5 rounded-full ${
                unread > 0 ? 'bg-accent' : 'bg-transparent'
              }`}
              aria-hidden="true"
            />
            <CharacterAvatar
              identity={identity}
              name={name}
              imageUrl={peer?.avatar_url ?? null}
              size="sm"
            />
            <span className="min-w-0 flex-1">
              <span
                className={`block truncate text-[13px] ${
                  unread > 0 ? 'font-semibold text-content' : 'font-medium'
                }`}
              >
                {name}
              </span>
              <span className="block truncate text-[11px] leading-relaxed text-content-faint">
                {item.last_message?.text_preview ?? '还没有消息'}
              </span>
            </span>
            {unread > 0 ? (
              <span className="tabular shrink-0 rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-accent-ink">
                {unread}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function MessageScroller({
  messages,
  playerId,
  resolveName,
  hasOlder,
  isLoadingOlder,
  onLoadOlder,
}: {
  readonly messages: readonly PlayerMessageView[];
  readonly playerId: string;
  readonly resolveName: (identity: string) => string;
  readonly hasOlder: boolean;
  readonly isLoadingOlder: boolean;
  readonly onLoadOlder: () => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);

  // 会话默认停在最新消息。已经在往回翻阅时不抢滚动位置，否则每 4 秒的
  // 增量轮询都会把使用者拉回底部。
  const pinnedToBottom = useRef(true);
  useEffect(() => {
    const element = viewport.current;
    if (element === null || !pinnedToBottom.current) return;
    element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  if (messages.length === 0) {
    return <EmptyState title="还没有消息" description="发送一条消息开始对话。" />;
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
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
    >
      {hasOlder ? (
        <button
          type="button"
          onClick={onLoadOlder}
          disabled={isLoadingOlder}
          className="mx-auto mb-1 rounded border border-border-subtle px-2.5 py-1 text-[11px] text-content-faint hover:text-content disabled:opacity-50"
        >
          {isLoadingOlder ? '正在读取…' : '读取更早的消息'}
        </button>
      ) : null}
      {groups.map((group, index) => (
        <div key={`${senderKey(group.sender)}-${index}`} className="animate-rise-in">
          <MessageGroupView group={group} playerId={playerId} resolveMentionName={resolveName} />
        </div>
      ))}
    </div>
  );
}
