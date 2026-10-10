import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { Plus, Users } from 'lucide-react';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { Composer, type ComposerTarget } from '@/components/Composer';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { MessageGroupView, useSettledThrough } from '@/components/MessageGroup';
import { NewConversationDialog } from '@/components/NewConversationDialog';
import { TurnStatusLane } from '@/components/TurnStatusLane';
import { Shell } from '@/components/Shell';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { deriveTurnStates } from '@/lib/deriveTurnStates';
import { resolveCover } from '@/lib/coverPresets';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';
import { groupMessages, senderKey } from '@/lib/groupMessages';
import { useConversationMembers, type PublicDisplay } from '@/api/directory';
import {
  mergeMessages,
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
  const { subject } = useCurrentSubject();
  return <ChatSession key={JSON.stringify([subject.playerId, conversationId])} />;
}

function ChatSession() {
  const { conversationId = '' } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { subject } = useCurrentSubject();
  const playerId = subject.playerId;
  const [creating, setCreating] = useState(false);
  // 窄屏会话列表收起为抽屉，选中会话后自动收起，让消息流占满屏幕。
  const [listOpen, setListOpen] = useState(false);

  // 角色档案的「开始聊天」带着角色 id 跳到这里，自动打开并预选私聊。
  const inviteCharacterId =
    typeof location.state === 'object' &&
    location.state !== null &&
    'inviteCharacterId' in location.state &&
    typeof location.state.inviteCharacterId === 'string'
      ? location.state.inviteCharacterId
      : null;
  useEffect(() => {
    if (inviteCharacterId !== null && playerId !== '') setCreating(true);
  }, [inviteCharacterId, playerId]);
  const closeCreating = () => {
    setCreating(false);
    if (inviteCharacterId !== null) {
      // 消费掉一次性的跳转意图，刷新或关闭后不再自动弹出。
      navigate(location.pathname, { replace: true, state: null });
    }
  };

  const list = useConversationList(playerId, subject.communityId);
  const active = list.data?.items.find((item) => item.conversation_id === conversationId);

  const members = useConversationMembers(playerId, conversationId);
  const memberList = useMemo(() => members.data?.items ?? [], [members.data?.items]);

  const history = useConversationHistory(playerId, conversationId);
  const pollCursor = history.data?.pages[0]?.poll_cursor ?? null;
  const poll = useMessagePoll(playerId, conversationId, pollCursor, conversationId !== '');
  const turns = useTurns(playerId, conversationId, conversationId !== '');
  const markRead = useMarkRead(playerId);
  const send = useSendMessage(playerId, conversationId);

  const messages = useMemo(() => {
    const base = history.data?.pages.flatMap((page) => page.messages) ?? [];
    const fresh = poll.data?.messages ?? [];
    return mergeMessages(base, fresh);
  }, [history.data, poll.data]);


  // 会话成员用于人数和提及候选，标题由服务端摘要统一提供。
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
          avatarUrl: resolveOfficialAvatar({
            avatarUrl: member.avatar_url,
            displayName: member.display_name,
          }),
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
        setListOpen(false);
        void navigate(`/app/chat/${id}`);
      }}
      onCreate={() => {
        setListOpen(false);
        setCreating(true);
      }}
      canCreate={subject.communityId !== null}
    />
  );

  if (playerId === '') {
    return (
      <Shell
        section="chat"
        list={listColumn}
        mobileList={{ open: listOpen, onOpenChange: setListOpen }}
      >
        <EmptyState title="先登记身份" description="身份决定能看到哪些会话，从顶栏的「身份」进入。" />
      </Shell>
    );
  }

  return (
    <Shell
      section="chat"
      list={listColumn}
      mobileList={{ open: listOpen, onOpenChange: setListOpen }}
    >
      {creating ? (
        <NewConversationDialog
          onClose={closeCreating}
          initial={
            inviteCharacterId !== null
              ? { kind: 'direct', characterId: inviteCharacterId }
              : undefined
          }
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
          {history.error !== null ? <ErrorNotice error={history.error} /> : null}
          {poll.error !== null ? <ErrorNotice error={poll.error} /> : null}
          <MessageScroller
            key={conversationId}
            messages={messages}
            playerId={playerId}
            resolveName={nameOfIdentity}
            hasOlder={history.hasNextPage}
            isLoadingOlder={history.isFetching}
            onLoadOlder={() => {
              if (!history.hasNextPage || history.isFetching) return;
              void history.fetchNextPage();
            }}
          />
          <div className="shrink-0 border-t border-border-subtle px-5 py-3.5">
            <div className="w-full">
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
  const title = summary.display_name;
  const isGroup = summary.kind === 'group';
  // 群聊没有独立头像，用所属社群的场景封面缩略，让会话与世界氛围一致。
  const cover = isGroup ? resolveCover(summary.community_id, title) : null;

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
            {isGroup ? '群聊' : '私聊'}
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
      <div className="flex shrink-0 items-center justify-between px-4 py-3.5">
        <span className="text-[13px] font-semibold text-content-muted">会话</span>
        {canCreate ? (
          <button
            type="button"
            onClick={onCreate}
            title="新建会话"
            className="flex items-center gap-1 rounded-full border border-accent/40 bg-accent-soft px-3 py-1 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
          >
            <Plus className="size-3" strokeWidth={2.2} />
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
        const name = item.display_name;
        const identity = peer === null ? `group:${item.conversation_id}` : actorIdentity(peer);
        const unread = item.unread_count;
        return (
          <button
            key={item.conversation_id}
            type="button"
            onClick={() => {
              onSelect(item.conversation_id);
            }}
            className={`relative mx-2 mb-0.5 flex w-[calc(100%-1rem)] items-center gap-2.5 rounded-xl py-2.5 pl-3.5 pr-3 text-left transition-colors ${
              item.conversation_id === activeId
                ? 'bg-accent-soft'
                : 'hover:bg-white/5'
            }`}
          >
            {/*
             * 未读用左侧竖条而不是圆点。深色界面上圆点容易被头像吞掉，
             * 竖条贴着列表项边缘，未读与已读的分界一眼可见。
             */}
            <span
              className={`absolute inset-y-2 left-0 w-0.5 rounded-full ${
                unread > 0 ? 'bg-accent' : 'bg-transparent'
              }`}
              aria-hidden="true"
            />
            <CharacterAvatar
              identity={identity}
              name={name}
              imageUrl={resolveOfficialAvatar({
                avatarUrl: peer?.avatar_url,
                displayName: name,
              })}
              size="sm"
            />
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-2">
                <span
                  className={`min-w-0 flex-1 truncate text-[13px] ${
                    unread > 0 ? 'font-semibold text-content' : 'font-medium'
                  }`}
                >
                  {name}
                </span>
                {item.last_visible_message_at_utc !== null ? (
                  <span className="tabular shrink-0 text-[10px] text-content-faint">
                    {formatListTime(item.last_visible_message_at_utc)}
                  </span>
                ) : null}
              </span>
              <span className="mt-0.5 flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[11px] leading-relaxed text-content-faint">
                  {item.last_message?.text_preview ?? '还没有消息'}
                </span>
                {unread > 0 ? (
                  <span className="tabular shrink-0 rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-accent-ink">
                    {unread}
                  </span>
                ) : null}
              </span>
            </span>
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
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * 会话列表时间。当天显示时:分，更早显示月/日，只取本地呈现需要的精度。
 */
function formatListTime(isoUtc: string): string {
  const parsed = new Date(isoUtc);
  if (Number.isNaN(parsed.getTime())) return '';
  const now = new Date();
  const sameDay =
    parsed.getFullYear() === now.getFullYear() &&
    parsed.getMonth() === now.getMonth() &&
    parsed.getDate() === now.getDate();
  const pad = (value: number) => `${value}`.padStart(2, '0');
  if (sameDay) return `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
  return `${parsed.getMonth() + 1}/${parsed.getDate()}`;
}
