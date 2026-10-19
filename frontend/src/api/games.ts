import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { ApiError, request, type SchemaOf } from './http';
import { queryKeys } from './queryKeys';

export type GameSession = SchemaOf<'GameSessionResponse'>;
export type GameStatus = SchemaOf<'GameStatus'>;
export type GameType = SchemaOf<'GameTypeResponse'>;
export type GameOperation = SchemaOf<'GameOperationResponse'>;

type GomokuViewPayload = SchemaOf<'GameView_GomokuState_PlaceStoneAction_'>;
type AeroplaneViewPayload = SchemaOf<
  'GameView_AeroplaneState_Annotated_Union_RollDiceAction__TakeOffAction__MovePlaneAction__JumpFourAction__FlyShortcutAction__EndMoveAction__ReturnPenaltyAction___FieldInfo_annotation_NoneType__required_True__discriminator__type____'
>;
type KingdominoViewPayload = SchemaOf<
  'GameView_KingdominoBoard_Annotated_Union_PlaceInitialKingAction__PlaceDominoAction__ChooseDominoAction__DiscardDominoAction___FieldInfo_annotation_NoneType__required_True__discriminator__type____'
>;

// 契约把 game_type 生成为宽泛的 string，而每种玩法视图只会来自对应玩法，
// 前端把它收窄成字面量，得到可按 game_type 判别的联合，便于各玩法棋盘取自己的 state。
export type GameView =
  | (Omit<GomokuViewPayload, 'game_type'> & { game_type: 'gomoku' })
  | (Omit<AeroplaneViewPayload, 'game_type'> & { game_type: 'aeroplane' })
  | (Omit<KingdominoViewPayload, 'game_type'> & { game_type: 'kingdomino' });

// 各玩法的动作在契约里是判别联合；提交侧按字段比对判定合法性，因此这里汇总成一个联合。
export type GameAction =
  | SchemaOf<'PlaceStoneAction'>
  | SchemaOf<'RollDiceAction'>
  | SchemaOf<'TakeOffAction'>
  | SchemaOf<'MovePlaneAction'>
  | SchemaOf<'JumpFourAction'>
  | SchemaOf<'FlyShortcutAction'>
  | SchemaOf<'EndMoveAction'>
  | SchemaOf<'ReturnPenaltyAction'>
  | SchemaOf<'PlaceInitialKingAction'>
  | SchemaOf<'PlaceDominoAction'>
  | SchemaOf<'ChooseDominoAction'>
  | SchemaOf<'DiscardDominoAction'>;
export type GameCreationInput = Omit<
  SchemaOf<'CreateGameRequest'>,
  'player_id' | 'community_id' | 'request_id'
>;

export const gameStatusLabels: Record<GameStatus, string> = {
  waiting: '等人入座',
  running: '对局中',
  finished: '已结算',
  cancelled: '已取消',
};

export function useGameTypes() {
  return useQuery({
    queryKey: queryKeys.games.types,
    queryFn: ({ signal }) => request<SchemaOf<'GameTypesResponse'>>('/api/game-types', { signal }),
    staleTime: Infinity,
  });
}

export function useGameList(
  playerId: string,
  communityId: string | null,
  gameType: string,
  status: GameStatus | '',
) {
  return useInfiniteQuery({
    queryKey: queryKeys.games.list(playerId, communityId ?? '', gameType, status),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<SchemaOf<'Page_GameSessionResponse_'>>('/api/games', {
        query: {
          player_id: playerId,
          community_id: communityId,
          game_type: gameType,
          status: status || null,
          cursor: pageParam,
          limit: 12,
        },
        signal,
      }),
    enabled: playerId !== '' && communityId !== null,
    getNextPageParam: (page) => (page.has_more ? (page.cursor ?? undefined) : undefined),
  });
}

export function useGameSession(playerId: string, communityId: string | null, gameId: string) {
  return useQuery({
    queryKey: queryKeys.games.session(playerId, communityId ?? '', gameId),
    queryFn: ({ signal }) =>
      request<GameSession>(`/api/games/${gameId}`, {
        query: { player_id: playerId },
        signal,
      }),
    enabled: playerId !== '' && gameId !== '',
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.game.status === 'waiting' &&
      query.state.data.game.seats.some((seat) =>
        seat.occupant?.participant_ref.startsWith('character:'),
      )
        ? 5000
        : false,
  });
}

export function useGameCharacterCandidates(
  playerId: string,
  session: GameSession,
  enabled: boolean,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.games.candidates(playerId, session.community_id, session.game.game_id),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      request<SchemaOf<'Page_GameCharacterCandidate_'>>(
        `/api/games/${session.game.game_id}/participant-candidates`,
        {
          query: { player_id: playerId, cursor: pageParam, limit: 20 },
          signal,
        },
      ),
    enabled: enabled && session.capabilities.can_invite,
    getNextPageParam: (page) => (page.has_more ? (page.cursor ?? undefined) : undefined),
    staleTime: 0,
    refetchInterval: enabled ? 5000 : false,
  });
}

export function useGameView(playerId: string, session: GameSession | undefined) {
  const gameId = session?.game.game_id ?? '';
  return useQuery({
    queryKey: queryKeys.games.view(
      playerId,
      session?.community_id ?? '',
      gameId,
      session?.self_participation_id ?? '',
    ),
    queryFn: ({ signal }) =>
      request<GameView>(`/api/games/${gameId}/view`, {
        query: { player_id: playerId },
        signal,
      }),
    enabled: !!session?.self_participation_id && session.game.status !== 'waiting',
    retry: false,
  });
}

type LifecycleBodies = {
  join: SchemaOf<'JoinGameRequest'>;
  leave: SchemaOf<'LeaveGameRequest'>;
  start: SchemaOf<'GameOperationRequest'>;
  resign: SchemaOf<'ResignGameRequest'>;
  cancel: SchemaOf<'CancelGameRequest'>;
  end: SchemaOf<'EndGameRequest'>;
};
export type GameLifecycleKind = keyof LifecycleBodies;
type OperationScope = { communityId: string; participationId: string | null };
export type PendingGameOperation = OperationScope &
  (
    | { kind: 'create'; body: SchemaOf<'CreateGameRequest'> }
    | {
        [K in GameLifecycleKind]: {
          kind: K;
          gameId: string;
          body: LifecycleBodies[K];
        };
      }[GameLifecycleKind]
    | {
        kind: 'action';
        gameId: string;
        body: SchemaOf<'SubmitGameActionRequest'>;
      }
  );
export type GameActionReceipt =
  | SchemaOf<'ActionReceipt_StonePlacedResult_'>
  | SchemaOf<'ActionReceipt_Union_DiceRolled__PlaneTookOff__PlaneWalked__PlaneJumped__PlaneFlew__PlaneSentBack__MoveEnded__'>
  | SchemaOf<'ActionReceipt_Union_InitialKingPlaced__DominoPlaced__DominoDiscarded__DominoChosen__'>;
export type GameOperationResult = GameOperation | GameActionReceipt;

const operationPaths: Record<GameLifecycleKind, string> = {
  join: 'participants',
  leave: 'leave',
  start: 'start',
  resign: 'resign',
  cancel: 'cancel',
  end: 'end',
};

export function sendGameOperation(operation: PendingGameOperation) {
  const path =
    operation.kind === 'create'
      ? '/api/games'
      : `/api/games/${operation.gameId}/${operation.kind === 'action' ? 'actions' : operationPaths[operation.kind]}`;
  return request<GameOperationResult>(path, {
    method: 'POST',
    body: operation.body,
  });
}

export async function readGameOperationReceipt(
  operation: Exclude<PendingGameOperation, { kind: 'create' }>,
) {
  const action = operation.kind === 'action';
  try {
    return await request<GameOperationResult>(
      `/api/games/${operation.gameId}/${action ? 'actions' : 'operations'}/${operation.body.request_id}`,
      {
        query: {
          player_id: operation.body.player_id,
          participation_id: action ? operation.participationId : null,
        },
      },
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
