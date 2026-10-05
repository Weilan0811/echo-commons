import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { Composer, type ComposerTarget } from '@/components/Composer';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { MessageGroupView } from '@/components/MessageGroup';
import { TurnStatusLane } from '@/components/TurnStatusLane';
import { Shell } from '@/components/Shell';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { deriveTurnStates } from '@/lib/deriveTurnStates';
import { groupMessages, senderKey } from '@/lib/groupMessages';
import { newClientMessageId } from '@/lib/clientMessageId';
import {
  fetchOlderPage,
  useConversationHistory,
  useConversationList,
  useMarkRead,
  useMessagePoll,
  useReadState,
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

  const list = useConversationList(playerId, subject.communityId);
  const active = list.data?.items.find((item) => item.conversation_id === conversationId);

  const history = useConversationHistory(playerId, conversationId);
  const [olderPages, setOlderPages] = useState<PlayerMessageView[]>([]);
  const pollCursor = history.data?.poll_cursor ?? null;
  const poll = useMessagePoll(playerId, conversationId, pollCursor, conversationId !== '');
  const turns = useTurns(playerId, conversationId, conversationId !== '');
  const readState = useReadState(playerId, conversationId, conversationId !== '');
  const markRead = useMarkRead(playerId, conversationId);
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

  // 展示新消息后推进阅读位置。契约说明读取本身不标记已读，因此需要显式提交。
  const lastVisible = messages[messages.length - 1];
  useEffect(() => {
    if (conversationId === '') return;
    if (lastVisible === undefined) return;
    if (readState.data?.last_read_sequence === lastVisible.sequence) return;
    if (document.visibilityState !== 'visible') return;
    markRead.mutate(lastVisible.message_id);
  }, [conversationId, lastVisible?.message_id, readState.data?.last_read_sequence]);

  // 发送者的显示名由后端给出，前端不再自行映射。
  const nameOf = useMemo(
    () => (sender: PlayerMessageView['sender']) =>
      sender.kind === 'system' ? '系统' : sender.actor_id,
    [],
  );

  const mentionTargets = useMemo<ComposerTarget[]>(() => {
    const peers = new Set<string>();
    for (const message of messages) {
      const key = senderKey(message.sender);
      if (key !== `player:${playerId}`) peers.add(key);
    }
    const names = new Map<string, string>();
    for (const message of messages) {
      names.set(senderKey(message.sender), message.sender_display.display_name);
    }
    return [...peers].map((identity) => ({
      identity,
      name: names.get(identity) ?? identity,
    }));
  }, [messages, playerId]);

  const listColumn = (
    <ConversationList
      summaries={list.data?.items ?? []}
      activeId={conversationId === '' ? null : conversationId}
      isLoading={list.isPending}
      error={list.error}
      onSelect={(id) => {
        void navigate(`/app/chat/${id}`);
      }}
    />
  );

  if (playerId === '') {
    return (
      <Shell section="chat" list={listColumn}>
        <EmptyState title="先选择身份" description="当前主体由主体与社群入口决定。" />
      </Shell>
    );
  }

  return (
    <Shell section="chat" list={listColumn}>
      {active === undefined ? (
        <EmptyState title="选择一个会话" description="左侧列表按最后可见消息时间排序。" />
      ) : (
        <>
          <ThreadHeader summary={active} playerId={playerId} />
          <MessageScroller
            messages={messages}
            playerId={playerId}
            nameOf={nameOf}
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
              resolveName={(id) => nameOf({ kind: 'character', actor_id: id })}
            />
            {active.can_send ? (
              <div className="mt-2">
                <Composer
                  currentPlayerId={playerId}
                  characters={mentionTargets}
                  onSend={async (draft) => {
                    await send.mutateAsync({
                      playerId,
                      clientMessageId: newClientMessageId(),
                      text: draft.text,
                      mentions: draft.mentions.map(
                        (identity): ActorRef => ({ kind: 'character', actor_id: identity }),
                      ),
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
  playerId,
}: {
  readonly summary: ConversationSummary;
  readonly playerId: string;
}) {
  const peer =
    summary.direct_peer === null || summary.direct_peer === undefined
      ? null
      : summary.direct_peer;
  const title = peer === null ? summary.conversation_id : peer.display_name;
  const past = summary.self_membership_status === 'past';

  return (
    <header className="flex shrink-0 items-center gap-2.5 border-b border-border-subtle px-4 py-3">
      {peer === null ? null : (
        <CharacterAvatar
          identity={`${peer.actor.kind}:${'actor_id' in peer.actor ? peer.actor.actor_id : peer.actor.source_id}`}
          name={peer.display_name}
          size="sm"
        />
      )}
      <span className="text-sm font-medium">{title}</span>
      <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
        {summary.kind === 'group' ? '群聊' : '私聊'}
      </span>
      {past ? (
        <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
          已离开
        </span>
      ) : null}
      <span className="ml-auto text-[11px] text-content-faint">
        {summary.unread_count > 0 ? `${summary.unread_count} 条未读` : playerId}
      </span>
    </header>
  );
}

function ConversationList({
  summaries,
  activeId,
  isLoading,
  error,
  onSelect,
}: {
  readonly summaries: readonly ConversationSummary[];
  readonly activeId: string | null;
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly onSelect: (conversationId: string) => void;
}) {
  if (error !== null && error !== undefined) {
    return (
      <div className="p-3">
        <ErrorNotice error={error} />
      </div>
    );
  }
  if (isLoading) {
    return <p className="p-3 text-xs text-content-faint">正在读取会话…</p>;
  }
  if (summaries.length === 0) {
    return <p className="p-3 text-xs text-content-faint">还没有会话。</p>;
  }

  const groups = summaries.filter((item) => item.kind === 'group');
  const directs = summaries.filter((item) => item.kind === 'direct');

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <ListSection title="群聊" items={groups} activeId={activeId} onSelect={onSelect} />
      <ListSection title="私聊" items={directs} activeId={activeId} onSelect={onSelect} />
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
  if (items.length === 0) return null;
  return (
    <div className="flex flex-col">
      <p className="px-3 pb-1 pt-3 text-[10px] uppercase tracking-wide text-content-faint">{title}</p>
      {items.map((item) => {
        const peer = item.direct_peer ?? null;
        const name = peer === null ? item.conversation_id : peer.display_name;
        const identity =
          peer === null
            ? item.community_id
            : `${peer.actor.kind}:${'actor_id' in peer.actor ? peer.actor.actor_id : peer.actor.source_id}`;
        return (
          <button
            key={item.conversation_id}
            type="button"
            onClick={() => {
              onSelect(item.conversation_id);
            }}
            className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
              item.conversation_id === activeId ? 'bg-surface-overlay' : 'hover:bg-surface-raised'
            }`}
          >
            <CharacterAvatar identity={identity} name={name} size="sm" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium">{name}</span>
              <span className="block truncate text-[11px] text-content-faint">
                {item.last_message?.text_preview ?? '还没有消息'}
              </span>
            </span>
            {item.unread_count > 0 ? (
              <span className="shrink-0 rounded-full bg-accent px-1.5 text-[10px] text-surface">
                {item.unread_count}
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
  nameOf,
  hasOlder,
  isLoadingOlder,
  onLoadOlder,
}: {
  readonly messages: readonly PlayerMessageView[];
  readonly playerId: string;
  readonly nameOf: (sender: PlayerMessageView['sender']) => string;
  readonly hasOlder: boolean;
  readonly isLoadingOlder: boolean;
  readonly onLoadOlder: () => void;
}) {
  if (messages.length === 0) {
    return <EmptyState title="还没有消息" description="发送一条消息开始对话。" />;
  }
  const groups = groupMessages(messages);
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
      {hasOlder ? (
        <button
          type="button"
          onClick={onLoadOlder}
          disabled={isLoadingOlder}
          className="mx-auto mb-3 rounded border border-border-subtle px-2.5 py-1 text-[11px] text-content-faint hover:text-content disabled:opacity-50"
        >
          {isLoadingOlder ? '正在读取…' : '读取更早的消息'}
        </button>
      ) : null}
      {groups.map((group, index) => (
        <div key={`${senderKey(group.sender)}-${index}`} className="animate-rise-in">
          <MessageGroupView group={group} playerId={playerId} resolveName={nameOf} />
        </div>
      ))}
    </div>
  );
}
