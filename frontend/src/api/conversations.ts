// 会话、消息与阅读位置的读取与写入。
//
// 三种消息读取各用其语义，不可互换：
// - 历史：首次取最新可见消息并固定扫描终点，older_cursor 向前翻，poll_cursor 交给增量读取。
// - 增量：带 cursor 读取新消息，无新消息时仍返回有效游标。
// - 轮次：用于状态栏，不返回不可见内容。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from './http';
import { queryKeys } from './queryKeys';

type PlayerMessageView = SchemaOf<'PlayerMessageView'>;
type MessageHistoryView = SchemaOf<'MessageHistoryView'>;
type MessagePageView = SchemaOf<'MessagePageView'>;
type ConversationSummary = SchemaOf<'PlayerConversationSummary'>;
type ReadState = SchemaOf<'ReadState'>;
type TurnView = SchemaOf<'TurnView'>;
type SendMessage = SchemaOf<'SendMessage'>;
type ActorRef = SchemaOf<'ActorRef'>;

export type { PlayerMessageView, ConversationSummary, ReadState, TurnView, ActorRef };

interface Page<T> {
  readonly items: T[];
  readonly cursor: string | null;
  readonly has_more: boolean;
}

/** 会话列表轮询间隔。与角色回应的秒级耗时相比，过快没有意义。 */
const POLL_INTERVAL_MS = 4000;

/** 会话列表。摘要已含最后可见消息、阅读位置与未读数，不需要逐个查询成员。 */
export function useConversationList(
  playerId: string,
  communityId: string | null,
  membership = 'current',
  status = 'active',
) {
  return useQuery({
    queryKey: queryKeys.conversations.list(playerId, communityId, membership, status),
    queryFn: () =>
      request<Page<ConversationSummary>>('/api/conversations', {
        query: { player_id: playerId, community_id: communityId, membership, status },
      }),
    enabled: playerId !== '',
    // 会话列表不依赖消息轮询，节奏可以更慢。
    refetchInterval: POLL_INTERVAL_MS * 2,
  });
}

/**
 * 历史读取。首次不传游标，返回最新可见消息与增量位置。
 * 之后按 older_cursor 继续向前翻；翻页使用 queryFn 手动触发，不参与自动轮询。
 */
export function useConversationHistory(playerId: string, conversationId: string) {
  return useQuery({
    queryKey: queryKeys.conversations.history(playerId, conversationId),
    queryFn: () =>
      request<MessageHistoryView>(`/api/conversations/${conversationId}/messages/history`, {
        query: { player_id: playerId },
      }),
    enabled: playerId !== '' && conversationId !== '',
    staleTime: Infinity,
  });
}

/** 按 older_cursor 读取更早的一页历史。 */
export async function fetchOlderPage(
  playerId: string,
  conversationId: string,
  olderCursor: string,
): Promise<MessageHistoryView> {
  return request<MessageHistoryView>(`/api/conversations/${conversationId}/messages/history`, {
    query: { player_id: playerId, older_cursor: olderCursor },
  });
}

/**
 * 增量轮询。游标来自历史接口首次返回的 poll_cursor。
 *
 * 契约说明读取与后台轮询不标记已读，因此这里不会推进阅读位置。
 */
export function useMessagePoll(
  playerId: string,
  conversationId: string,
  pollCursor: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.conversations.poll(playerId, conversationId),
    queryFn: () =>
      request<MessagePageView>(`/api/conversations/${conversationId}/messages`, {
        query: { player_id: playerId, cursor: pollCursor },
      }),
    enabled: enabled && playerId !== '' && conversationId !== '' && pollCursor !== null,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

/** 轮次读取，用于状态栏。不可见内容不返回。 */
export function useTurns(playerId: string, conversationId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.conversations.turns(playerId, conversationId),
    queryFn: () =>
      request<readonly TurnView[]>(`/api/conversations/${conversationId}/turns`, {
        query: { player_id: playerId },
      }),
    enabled: enabled && playerId !== '' && conversationId !== '',
    refetchInterval: POLL_INTERVAL_MS,
  });
}

/** 阅读位置。 */
export function useReadState(playerId: string, conversationId: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.conversations.read(playerId, conversationId),
    queryFn: () =>
      request<ReadState>(`/api/conversations/${conversationId}/read`, { method: 'PUT' }),
    enabled: enabled && playerId !== '' && conversationId !== '',
  });
}

/**
 * 标记已读。位置只向前推进，重复提交较旧位置不会倒退，因此可以安全地
 * 在每次展示新消息后调用。
 */
export function useMarkRead(playerId: string, conversationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (throughMessageId: string) =>
      request<ReadState>(`/api/conversations/${conversationId}/read`, {
        method: 'PUT',
        body: { player_id: playerId, through_message_id: throughMessageId } satisfies {
          player_id: string;
          through_message_id: string;
        },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.conversations.read(playerId, conversationId) });
      void client.invalidateQueries({ queryKey: queryKeys.conversations.list(playerId, '', '', '') });
    },
  });
}

export interface SendInput {
  readonly playerId: string;
  readonly clientMessageId: string;
  readonly text: string;
  readonly mentions: readonly ActorRef[];
  readonly replyToMessageId: string | null;
}

/** 发送消息。契约不接受可见范围与受众字段，携带会返回 422。 */
export function useSendMessage(playerId: string, conversationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: SendInput) => {
      const body: SendMessage = {
        player_id: input.playerId,
        client_message_id: input.clientMessageId,
        text: input.text,
        mentions: [...input.mentions],
        reply_to_message_id: input.replyToMessageId,
      };
      return request(`/api/conversations/${conversationId}/messages`, {
        method: 'POST',
        body,
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.conversations.poll(playerId, conversationId) });
    },
  });
}
