// 会话、消息与阅读位置的读取与写入。
//
// 三种消息读取各用其语义，不可互换：
// - 历史：首次取最新可见消息并固定扫描终点，older_cursor 向前翻，poll_cursor 交给增量读取。
// - 增量：带 cursor 读取新消息，无新消息时仍返回有效游标。
// - 轮次：用于状态栏，不返回不可见内容。
import { useRef } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { newClientMessageId } from '@/lib/clientMessageId';
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
  });
}

/**
 * 历史读取。首次不传游标，返回最新可见消息与增量位置。
 * 之后按 older_cursor 继续向前翻，查询缓存保留每页结果，不参与自动轮询。
 */
export function useConversationHistory(playerId: string, conversationId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.conversations.history(playerId, conversationId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<MessageHistoryView>(`/api/conversations/${conversationId}/messages/history`, {
        query: { player_id: playerId, older_cursor: pageParam },
        signal,
      }),
    getNextPageParam: (page) => page.has_older ? page.older_cursor ?? undefined : undefined,
    enabled: playerId !== '' && conversationId !== '',
    staleTime: Infinity,
  });
}

export interface PolledMessages {
  initialCursor: string;
  cursor: string;
  messages: PlayerMessageView[];
}

/** 历史与增量可能重叠，统一按消息编号去重，再按会话序号展示。 */
export function mergeMessages(...pages: readonly (readonly PlayerMessageView[])[]) {
  const messages = new Map<string, PlayerMessageView>();
  for (const page of pages) {
    for (const message of page) messages.set(message.message_id, message);
  }
  return [...messages.values()].sort((left, right) => left.sequence - right.sequence);
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
  const client = useQueryClient();
  const queryKey = queryKeys.conversations.poll(playerId, conversationId);
  return useQuery({
    queryKey,
    queryFn: async ({ signal }): Promise<PolledMessages> => {
      const previous = client.getQueryData<PolledMessages>(queryKey);
      const retained = previous?.initialCursor === pollCursor ? previous : undefined;
      let cursor = retained?.cursor ?? pollCursor!;
      let messages = retained?.messages ?? [];
      let hasMore: boolean;
      // 过滤后即使返回空页，也要继续推进服务端扫描位置。
      do {
        const page = await request<MessagePageView>(`/api/conversations/${conversationId}/messages`, {
          query: { player_id: playerId, cursor },
          signal,
        });
        messages = mergeMessages(messages, page.messages);
        cursor = page.cursor;
        hasMore = page.has_more;
      } while (hasMore);
      return { initialCursor: pollCursor!, cursor, messages };
    },
    enabled: enabled && playerId !== '' && conversationId !== '' && pollCursor !== null,
    staleTime: Infinity,
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
  });
}

/** 阅读位置。契约只提供写入，没有单独读取；已读情况由会话摘要给出。 */
export function useMarkRead(playerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { conversationId: string; throughMessageId: string }) =>
      request<ReadState>(`/api/conversations/${input.conversationId}/read`, {
        method: 'PUT',
        body: {
          player_id: playerId,
          through_message_id: input.throughMessageId,
        } satisfies {
          player_id: string;
          through_message_id: string;
        },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.conversations.lists(playerId) });
    },
  });
}

export interface SendInput {
  readonly text: string;
  readonly mentions: readonly ActorRef[];
  readonly replyToMessageId: string | null;
}

/** 发送消息。契约不接受可见范围与受众字段，携带会返回 422。 */
export function useSendMessage(playerId: string, conversationId: string) {
  const client = useQueryClient();
  const pending = useRef<{ scope: string; content: string; body: SendMessage } | null>(null);
  return useMutation({
    networkMode: 'always',
    mutationFn: async (input: SendInput) => {
      const content = JSON.stringify(input);
      const scope = JSON.stringify([playerId, conversationId]);
      if (pending.current?.scope !== scope || pending.current.content !== content) {
        // 结果未知时保留完整请求；相同内容的重试复用服务端幂等编号。
        pending.current = {
          scope,
          content,
          body: {
            player_id: playerId,
            client_message_id: newClientMessageId(),
            text: input.text,
            mentions: [...input.mentions],
            reply_to_message_id: input.replyToMessageId,
          },
        };
      }
      const attempt = pending.current;
      const result = await request(`/api/conversations/${conversationId}/messages`, {
        method: 'POST',
        body: attempt.body,
      });
      if (pending.current === attempt) pending.current = null;
      return result;
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.conversations.poll(playerId, conversationId) });
    },
  });
}
