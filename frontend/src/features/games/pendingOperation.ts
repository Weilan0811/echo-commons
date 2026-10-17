import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/api/http';
import { queryKeys } from '@/api/queryKeys';
import { errorMessage } from '@/components/ErrorNotice';
import {
  readGameOperationReceipt,
  sendGameOperation,
  type GameOperationResult,
  type PendingGameOperation,
} from '@/api/games';

export function pendingOperationKey(playerId: string, communityId: string, resource: string) {
  return `echo-commons.game-operation:${JSON.stringify([playerId, communityId, resource])}`;
}

export function operationRejected(error: unknown) {
  return (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  );
}

export function operationErrorMessage(error: unknown) {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '操作未完成';
  const messages: Record<string, string> = {
    state_version_conflict: '棋局已经变化，已重新读取。请查看后重新操作。',
    opportunity_expired: '这一轮的落子机会已经失效，已重新读取棋局。',
    not_current_actor: '当前没有轮到你，请等待对方落子。',
    illegal_action: '这个位置无法落子，请选择空交点。',
    operation_forbidden: '当前没有执行这项操作的资格。',
    game_finished: '这一局已经结束，已重新读取结果。',
    game_already_started: '这一局已经开始，已重新读取当前状态。',
    game_not_started: '这一局尚未开始，请等待创建者开始对局。',
    game_not_ready: '参与者尚未到齐，暂时无法开始。',
    seat_occupied: '这个席位已经有人，已重新读取席位。',
    participant_already_seated: '目标参与者已经入座，已重新读取当前席位。',
    participation_not_found: '目标参与记录已失效，请查看当前席位。',
    character_memory_not_ready: '角色记忆尚未准备完成，请查看角色状态。',
    conflict: '活动状态已经变化，已重新读取。请查看后重新操作。',
    idempotency_conflict: '原请求编号与请求内容不一致，请检查保存的操作。',
  };
  return messages[error.code] ?? errorMessage(error);
}

// 请求正文先保存，再发送。回执只确认执行结果，当前棋局始终重新向后端读取。
export function usePendingGameOperation(
  playerId: string,
  communityId: string,
  resource: string,
  enabled = true,
) {
  const client = useQueryClient();
  const key = pendingOperationKey(playerId, communityId, resource);
  const [initial] = useState(() => {
    try {
      const raw = sessionStorage.getItem(key);
      return {
        operation: raw ? (JSON.parse(raw) as PendingGameOperation) : null,
        error: null as unknown,
      };
    } catch (error) {
      return { operation: null, error };
    }
  });
  const [pending, setPending] = useState(initial.operation);
  const [isSending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(initial.error);
  const [result, setResult] = useState<GameOperationResult | null>(null);
  const busy = useRef(false);
  const mounted = useRef(false);
  const current = useRef(initial.operation);

  const refresh = useCallback(async () => {
    await Promise.all([
      client.invalidateQueries({
        queryKey: queryKeys.games.scope(playerId, communityId),
      }),
      client.invalidateQueries({
        queryKey: queryKeys.conversations.lists(playerId),
      }),
      client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === 'conversations' &&
          query.queryKey.includes(playerId) &&
          query.queryKey.includes('detail'),
      }),
    ]);
  }, [client, playerId, communityId]);

  const execute = useCallback(
    async (operation: PendingGameOperation, recovering: boolean) => {
      if (busy.current) return;
      busy.current = true;
      setSending(true);
      setError(null);
      let rejected = false;
      try {
        let receipt =
          recovering && operation.kind !== 'create'
            ? await readGameOperationReceipt(operation)
            : null;
        if (!receipt) {
          try {
            receipt = await sendGameOperation(operation);
          } catch (cause) {
            rejected = operationRejected(cause);
            throw cause;
          }
        }
        sessionStorage.removeItem(key);
        current.current = null;
        if (mounted.current) {
          setPending(null);
          setResult(receipt);
        }
        await refresh();
      } catch (cause) {
        if (rejected) {
          sessionStorage.removeItem(key);
          current.current = null;
          if (mounted.current) setPending(null);
          await refresh();
        }
        if (mounted.current) setError(cause);
      } finally {
        busy.current = false;
        if (mounted.current) setSending(false);
      }
    },
    [key, refresh],
  );

  useEffect(() => {
    mounted.current = true;
    if (enabled && current.current) void execute(current.current, true);
    const online = () => {
      if (enabled && current.current) void execute(current.current, true);
    };
    window.addEventListener('online', online);
    return () => {
      mounted.current = false;
      window.removeEventListener('online', online);
    };
  }, [enabled, execute]);

  function submit(operation: PendingGameOperation) {
    if (!enabled || busy.current || current.current) return;
    try {
      sessionStorage.setItem(key, JSON.stringify(operation));
      current.current = operation;
      setPending(operation);
      setResult(null);
    } catch {
      setError(new Error('浏览器无法保存待确认操作，请允许当前页面使用标签页存储后重试。'));
      return;
    }
    void execute(operation, false);
  }
  return {
    submit,
    pending,
    isSending,
    result,
    error,
    blocked: !!pending || isSending || !!initial.error,
    recover: () => {
      if (enabled && current.current) void execute(current.current, true);
    },
    refresh,
  };
}
