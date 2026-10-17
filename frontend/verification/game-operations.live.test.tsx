import { randomUUID } from 'node:crypto';
import { beforeAll, describe, expect, it } from 'vitest';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { request } from '@/api/http';
import {
  useGameSession,
  useGameView,
  type GameOperation,
  type GameSession,
  type GameView,
  type PendingGameOperation,
} from '@/api/games';
import { actionOperation, lifecycleOperation } from '@/features/games/operations';
import { pendingOperationKey, usePendingGameOperation } from '@/features/games/pendingOperation';

const suffix = randomUUID();
const alice = `game-check-alice-${suffix}`;
const bob = `game-check-bob-${suffix}`;
const communityId = `game-check-${suffix}`;
const post = <T,>(path: string, body: unknown) => request<T>(path, { method: 'POST', body });
const readSession = (gameId: string, player = alice) =>
  request<GameSession>(`/api/games/${gameId}`, { query: { player_id: player } });

beforeAll(async () => {
  if (!import.meta.env.VITE_API_BASE_URL)
    throw new Error('请通过 VITE_API_BASE_URL 指定真实测试后端。');
  await post('/api/players', { player_id: alice, display_name: '操作验证甲' });
  await post('/api/players', { player_id: bob, display_name: '操作验证乙' });
  await post('/api/communities', {
    player_id: alice,
    community_id: communityId,
    name: '操作恢复验证',
    timezone: 'UTC',
  });
  await request(`/api/communities/${communityId}/players/${bob}`, { method: 'PUT' });
});

function mountOperation(playerId: string, resource: string, readGame = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () => {
      const session = useGameSession(
        readGame ? playerId : '',
        communityId,
        readGame ? resource : '',
      );
      const view = useGameView(playerId, session.data);
      return { operation: usePendingGameOperation(playerId, communityId, resource), session, view };
    },
    { wrapper },
  );
  return {
    ...hook,
    close: () => {
      hook.unmount();
      client.clear();
      cleanup();
    },
  };
}

function save(resource: string, operation: PendingGameOperation) {
  const key = pendingOperationKey(operation.body.player_id, communityId, resource);
  sessionStorage.setItem(key, JSON.stringify(operation));
  return key;
}

async function create() {
  return post<GameOperation>('/api/games', {
    player_id: alice,
    community_id: communityId,
    request_id: randomUUID(),
  });
}

describe('真实后端的操作恢复', () => {
  it('刷新前保存的创建请求恢复为同一对局，重复恢复不增加对局', async () => {
    const original: PendingGameOperation = {
      kind: 'create',
      communityId,
      participationId: null,
      body: {
        player_id: alice,
        community_id: communityId,
        request_id: randomUUID(),
        game_type: 'gomoku',
        ruleset_id: 'gomoku.freestyle',
        ruleset_version: 1,
        initial_seat_id: 'black',
        config: {},
      },
    };
    const applied = await post<GameOperation>('/api/games', original.body);
    const key = save('create:gomoku', original);
    const hook = mountOperation(alice, 'create:gomoku');
    try {
      await waitFor(() =>
        expect(hook.result.current.operation.result?.game_id).toBe(applied.game_id),
      );
      expect(sessionStorage.getItem(key)).toBeNull();
      const again = await post<GameOperation>('/api/games', original.body);
      expect(again).toEqual(applied);
    } finally {
      hook.close();
    }
  });

  it('已执行的旧落子通过原回执恢复，页面保留较新局势', async () => {
    const game = await create();
    const initial = await readSession(game.game_id, bob);
    await post(
      `/api/games/${game.game_id}/participants`,
      lifecycleOperation('join', initial, bob, 'white').body,
    );
    const start = lifecycleOperation('start', await readSession(game.game_id), alice);
    await post(`/api/games/${game.game_id}/start`, start.body);
    const session = await readSession(game.game_id);
    const firstView = await request<GameView>(`/api/games/${game.game_id}/view`, {
      query: { player_id: alice },
    });
    const first = actionOperation(session, firstView, alice, { type: 'place_stone', x: 7, y: 7 })!;
    const receipt = await post(`/api/games/${game.game_id}/actions`, first.body);
    const bobView = await request<GameView>(`/api/games/${game.game_id}/view`, {
      query: { player_id: bob },
    });
    const second = actionOperation(await readSession(game.game_id, bob), bobView, bob, {
      type: 'place_stone',
      x: 8,
      y: 7,
    })!;
    await post(`/api/games/${game.game_id}/actions`, second.body);
    const key = save(game.game_id, first);
    const hook = mountOperation(alice, game.game_id, true);
    try {
      await waitFor(() => expect(hook.result.current.operation.result).toEqual(receipt));
      await waitFor(() => expect(hook.result.current.view.data?.state.stones).toHaveLength(2));
      expect(hook.result.current.view.data!.state_version).toBe(bobView.state_version + 1);
      expect(sessionStorage.getItem(key)).toBeNull();
      const stale = actionOperation(session, firstView, alice, {
        type: 'place_stone',
        x: 6,
        y: 7,
      })!;
      hook.result.current.operation.submit(stale);
      await waitFor(() => expect(hook.result.current.operation.error).toBeTruthy());
      expect(hook.result.current.operation.pending).toBeNull();
      expect(sessionStorage.getItem(key)).toBeNull();
      expect(
        (
          await request<GameView>(`/api/games/${game.game_id}/view`, {
            query: { player_id: alice },
          })
        ).state.stones,
      ).toHaveLength(2);
    } finally {
      hook.close();
    }
  });

  it('已开始对局的原生命周期回执仍可恢复', async () => {
    const game = await create();
    await post(
      `/api/games/${game.game_id}/participants`,
      lifecycleOperation('join', await readSession(game.game_id), bob, 'white').body,
    );
    const operation = lifecycleOperation('start', await readSession(game.game_id), alice);
    const receipt = await post(`/api/games/${game.game_id}/start`, operation.body);
    save(game.game_id, operation);
    const hook = mountOperation(alice, game.game_id, true);
    try {
      await waitFor(() => expect(hook.result.current.operation.result).toEqual(receipt));
      await waitFor(() => expect(hook.result.current.session.data?.game.status).toBe('running'));
    } finally {
      hook.close();
    }
  });

  it('切换玩家后不读取、执行或清除另一玩家的待确认请求', async () => {
    const game = await create();
    const original = lifecycleOperation('cancel', await readSession(game.game_id), alice);
    const key = save(game.game_id, original);
    const hook = mountOperation(bob, game.game_id);
    try {
      expect(hook.result.current.operation.pending).toBeNull();
      expect(hook.result.current.operation.result).toBeNull();
      expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(original);
      expect((await readSession(game.game_id)).game.status).toBe('waiting');
    } finally {
      sessionStorage.removeItem(key);
      hook.close();
    }
  });
});
