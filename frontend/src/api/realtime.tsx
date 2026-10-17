import { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient, type Query } from '@tanstack/react-query';
import { ApiError, apiBaseUrl, request, type SchemaOf } from './http';
import { mergeMessages, type PolledMessages } from './conversations';
import { queryKeys } from './queryKeys';
import { updateSubject } from '@/identity/currentSubject';
import { ErrorNotice } from '@/components/ErrorNotice';

const EVENTS = [
  'conversation.message_created',
  'conversation.turns_changed',
  'conversation.summary_changed',
  'conversation.members_changed',
  'conversation.read_changed',
  'community.status_changed',
  'community.appearance_changed',
  'character.appearance_changed',
  'game.changed',
] as const satisfies readonly (keyof SchemaOf<'EventPayloadMap'>)[];

export function CommunityRealtime({
  playerId,
  communityId,
  children,
}: {
  playerId: string;
  communityId: string;
  children: ReactNode;
}) {
  const client = useQueryClient();
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [connecting, setConnecting] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const scope = (query: Query) =>
    query.queryKey[0] === 'games'
      ? query.queryKey[1] === playerId && query.queryKey[2] === communityId
      : ['directory', 'communities', 'conversations'].includes(String(query.queryKey[0])) &&
        query.queryKey.includes(playerId);
  useEffect(() => {
    const controller = new AbortController();
    void request<SchemaOf<'CursorResponse'>>(`/api/communities/${communityId}/events/cursor`, {
      query: { player_id: playerId },
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setError(null);
        setCursor(result.cursor);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          if (cause instanceof ApiError && cause.status === 404)
            updateSubject({ communityId: null, communityName: null });
          else setError(cause);
        }
      });
    return () => controller.abort();
  }, [playerId, communityId, attempt]);

  useEffect(() => {
    if (cursor === null) return;
    let disposed = false;
    let position = cursor;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = 1000;
    const subscriptions = new Set<() => void>();
    async function waitForReads() {
      // 子页面在取得游标后才挂载，等待它们的初始读取完成后连接。
      await new Promise<void>((resolve) => {
        const done = () => {
          if (disposed || !client.isFetching({ predicate: scope })) {
            unsubscribe();
            subscriptions.delete(done);
            resolve();
          }
        };
        const unsubscribe = client.getQueryCache().subscribe(done);
        subscriptions.add(done);
        done();
      });
    }
    function connect() {
      if (disposed) return;
      if (!navigator.onLine) {
        setConnecting(true);
        return;
      }
      source?.close();
      const url = new URL(`/api/communities/${communityId}/events`, apiBaseUrl());
      url.searchParams.set('player_id', playerId);
      url.searchParams.set('cursor', position);
      const connection = new EventSource(url);
      source = connection;
      connection.onopen = () => {
        if (disposed) return;
        delay = 1000;
        setConnecting(false);
        setError(null);
      };
      connection.onerror = () => {
        if (disposed) return;
        connection.close();
        setConnecting(true);
        timer = setTimeout(() => {
          void reconnect();
        }, delay);
        delay = Math.min(delay * 2, 15000);
      };
      connection.addEventListener('checkpoint', (event) => {
        if (disposed) return;
        position = (event as MessageEvent).lastEventId || position;
      });
      for (const kind of EVENTS)
        connection.addEventListener(kind, (event) => {
          if (disposed) return;
          const message = event as MessageEvent<string>;
          position = message.lastEventId || position;
          if (kind === 'game.changed') {
            const game = JSON.parse(message.data) as SchemaOf<'EventPayloadMap'>['game.changed'];
            if (game.community_id !== communityId) return;
            // 结束已结算的活动不会增加棋局版本，仍需刷新会话状态与操作资格。
            void client.invalidateQueries({
              queryKey: queryKeys.games.lists(playerId, communityId),
            });
            void client.invalidateQueries({
              queryKey: queryKeys.games.detail(playerId, communityId, game.game_id),
            });
            return;
          }
          const data = JSON.parse(message.data) as {
            conversation_id?: string;
            message?: SchemaOf<'PlayerMessageView'>;
          };
          if (
            data.conversation_id &&
            [
              'conversation.summary_changed',
              'conversation.members_changed',
              'conversation.read_changed',
            ].includes(kind)
          ) {
            void client.invalidateQueries({
              queryKey: queryKeys.conversations.detail(playerId, data.conversation_id),
            });
            if (kind === 'conversation.members_changed') {
              void client.resetQueries({
                queryKey: queryKeys.conversations.history(playerId, data.conversation_id),
              });
              void client.resetQueries({
                queryKey: queryKeys.conversations.poll(playerId, data.conversation_id),
              });
            }
          }
          if (kind === 'conversation.message_created' && data.conversation_id && data.message) {
            const key = queryKeys.conversations.poll(playerId, data.conversation_id);
            const item = data.message;
            client.setQueryData<PolledMessages>(key, (previous) =>
              previous
                ? {
                    ...previous,
                    messages: mergeMessages(previous.messages, [item]),
                  }
                : undefined,
            );
            if (!client.getQueryData(key)) void client.invalidateQueries({ queryKey: key });
          }
          if (kind === 'conversation.turns_changed' && data.conversation_id) {
            void client.invalidateQueries({
              queryKey: queryKeys.conversations.turns(playerId, data.conversation_id),
            });
          } else if (kind === 'conversation.members_changed' && data.conversation_id) {
            void client.invalidateQueries({
              queryKey: queryKeys.directory.conversationMembers(playerId, data.conversation_id),
            });
          } else if (kind.startsWith('community.')) {
            void client.invalidateQueries({
              queryKey: queryKeys.directory.community(playerId, communityId),
            });
            void client.invalidateQueries({
              queryKey: queryKeys.directory.communities(playerId),
            });
          } else if (kind === 'character.appearance_changed') {
            void client.invalidateQueries({
              queryKey: queryKeys.directory.characters(playerId, communityId),
            });
            void client.invalidateQueries({
              predicate: (query) => scope(query) && query.queryKey.includes('members'),
            });
          }
          if (kind.startsWith('conversation.'))
            void client.invalidateQueries({
              queryKey: queryKeys.conversations.lists(playerId),
            });
        });
      connection.addEventListener('resync_required', () => {
        if (disposed) return;
        connection.close();
        setConnecting(true);
        void resync();
      });
      connection.addEventListener('access_revoked', () => {
        if (disposed) return;
        connection.close();
        void client
          .cancelQueries({ predicate: scope })
          .then(() => client.removeQueries({ predicate: scope }));
        updateSubject({ communityId: null, communityName: null });
      });
    }
    async function resync() {
      try {
        const fresh = await request<SchemaOf<'CursorResponse'>>(
          `/api/communities/${communityId}/events/cursor`,
          { query: { player_id: playerId } },
        );
        if (disposed) return;
        position = fresh.cursor;
        const cursors = (query: Query) =>
          scope(query) &&
          query.queryKey.some((part) =>
            ['list', 'history', 'poll', 'events', 'candidates'].includes(String(part)),
          );
        await Promise.all([
          client.resetQueries({ predicate: cursors }),
          client.invalidateQueries({
            predicate: (query) => scope(query) && !cursors(query),
          }),
        ]);
        await waitForReads();
        connect();
      } catch (cause) {
        if (!disposed) {
          if (cause instanceof ApiError && cause.status === 404) {
            await client.cancelQueries({ predicate: scope });
            client.removeQueries({ predicate: scope });
            if (!disposed) updateSubject({ communityId: null, communityName: null });
            return;
          }
          setError(cause);
          timer = setTimeout(() => {
            void resync();
          }, delay);
        }
      }
    }
    async function reconnect() {
      // 服务端在建立连接前也会检查成员身份，拒绝时不会发送流内事件。
      try {
        await request<SchemaOf<'CursorResponse'>>(`/api/communities/${communityId}/events/cursor`, {
          query: { player_id: playerId },
        });
        connect();
      } catch (cause) {
        if (disposed) return;
        if (cause instanceof ApiError && cause.status === 404) {
          await client.cancelQueries({ predicate: scope });
          client.removeQueries({ predicate: scope });
          if (!disposed) updateSubject({ communityId: null, communityName: null });
        } else
          timer = setTimeout(() => {
            void reconnect();
          }, delay);
      }
    }
    const offline = () => {
      source?.close();
      clearTimeout(timer);
      setConnecting(true);
    };
    const online = () => {
      clearTimeout(timer);
      void reconnect();
    };
    window.addEventListener('offline', offline);
    window.addEventListener('online', online);
    void waitForReads().then(connect);
    return () => {
      disposed = true;
      source?.close();
      clearTimeout(timer);
      window.removeEventListener('offline', offline);
      window.removeEventListener('online', online);
      for (const done of subscriptions) done();
    };
  }, [client, playerId, communityId, cursor]);

  if (cursor === null)
    return error ? (
      <div className="p-6">
        <ErrorNotice error={error} />
        <button
          onClick={() => setAttempt((value) => value + 1)}
          className="mt-3 rounded border px-3 py-2"
        >
          重新连接
        </button>
      </div>
    ) : (
      <p className="p-6 text-content-muted">正在读取社群…</p>
    );
  return (
    <>
      {connecting ? (
        <p
          role="status"
          className="fixed right-4 top-2 z-[70] rounded-lg bg-surface-overlay px-3 py-2 text-xs text-content-muted shadow"
        >
          连接恢复中，消息会在恢复后继续更新
        </p>
      ) : null}
      {children}
    </>
  );
}
