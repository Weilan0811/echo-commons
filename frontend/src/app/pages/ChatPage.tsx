import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { Plus } from 'lucide-react';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { NewConversationDialog } from '@/components/NewConversationDialog';
import { Shell } from '@/components/Shell';
import { ConversationPanel } from '@/features/chat/ConversationPanel';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';
import { senderKey } from '@/lib/groupMessages';
import { useConversationList, type ConversationSummary } from '@/api/conversations';

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

  const listView = new URLSearchParams(location.search).get('view') ?? 'active';
  const list = useConversationList(playerId, subject.communityId, listView);

  const listColumn = (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap gap-1 px-3 pt-3" aria-label="会话列表范围">
        {(
          [
            ['active', '活动'],
            ['history', '历史'],
            ['hidden', '隐藏'],
            ['archived', '已结束'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={listView === value}
            onClick={() => void navigate(`${location.pathname}?view=${value}`, { replace: true })}
            className={`rounded-full px-2.5 py-1 text-xs ${listView === value ? 'bg-accent-soft text-accent' : 'text-content-faint hover:text-content'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <ConversationList
        summaries={list.data?.pages.flatMap((page) => page.items) ?? []}
        activeId={conversationId === '' ? null : conversationId}
        isLoading={list.isPending}
        error={list.error}
        onSelect={(id) => {
          setListOpen(false);
          void navigate(`/app/chat/${id}?view=${listView}`);
        }}
        onCreate={() => {
          setListOpen(false);
          setCreating(true);
        }}
        canCreate={subject.communityId !== null}
      />
      {list.hasNextPage ? (
        <button
          type="button"
          disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}
          className="p-3 text-xs text-accent"
        >
          加载更多会话
        </button>
      ) : null}
    </div>
  );

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
      {playerId === '' ? (
        <EmptyState
          title="先登记身份"
          description="身份决定能看到哪些会话，从顶栏的「身份」进入。"
        />
      ) : conversationId === '' ? (
        <EmptyState
          title="选择一个会话"
          description={
            subject.communityId === null
              ? '先在顶栏的「社群」里选一个。'
              : '左侧列表按最后可见消息时间排序。'
          }
        />
      ) : (
        <ConversationPanel
          key={JSON.stringify([playerId, conversationId])}
          playerId={playerId}
          conversationId={conversationId}
        />
      )}
    </Shell>
  );
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

      {isLoading ? <p className="px-3 pb-3 text-xs text-content-faint">正在读取会话…</p> : null}

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
        const identity = peer === null ? `group:${item.conversation_id}` : senderKey(peer.actor);
        const unread = item.unread_count;
        return (
          <button
            key={item.conversation_id}
            type="button"
            onClick={() => {
              onSelect(item.conversation_id);
            }}
            className={`relative mx-2 mb-0.5 flex w-[calc(100%-1rem)] items-center gap-2.5 rounded-xl py-2.5 pl-3.5 pr-3 text-left transition-colors ${
              item.conversation_id === activeId ? 'bg-accent-soft' : 'hover:bg-white/5'
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
