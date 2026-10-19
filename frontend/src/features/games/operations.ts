import type { GameAction, GameLifecycleKind, GameSession, GameView, PendingGameOperation } from '@/api/games';

export function lifecycleOperation(
  kind: GameLifecycleKind,
  session: GameSession,
  playerId: string,
  seatId = '',
): PendingGameOperation {
  const common = {
    communityId: session.community_id,
    gameId: session.game.game_id,
    participationId: session.self_participation_id,
  };
  const body = {
    player_id: playerId,
    request_id: crypto.randomUUID(),
    expected_state_version: session.game.state_version,
  };
  switch (kind) {
    case 'join':
      return {
        ...common,
        kind,
        body: { ...body, seat_id: seatId, participant: { kind: 'player' } },
      };
    case 'leave':
    case 'resign': {
      if (!session.self_participation_id) throw new Error('请先加入对局');
      return {
        ...common,
        kind,
        body: { ...body, participation_id: session.self_participation_id },
      };
    }
    case 'cancel':
      return { ...common, kind, body: { ...body, reason: '创建者取消对局' } };
    case 'end':
      return {
        ...common,
        kind,
        body: {
          ...body,
          expected_conversation_version: session.conversation.state_version,
        },
      };
    case 'start':
      return { ...common, kind, body };
  }
}

export function inviteCharacterOperation(
  session: GameSession,
  playerId: string,
  seatId: string,
  characterId: string,
): PendingGameOperation {
  return {
    kind: 'join',
    communityId: session.community_id,
    gameId: session.game.game_id,
    participationId: null,
    body: {
      player_id: playerId,
      request_id: crypto.randomUUID(),
      expected_state_version: session.game.state_version,
      seat_id: seatId,
      participant: { kind: 'character', character_id: characterId },
    },
  };
}

export function withdrawCharacterOperation(
  session: GameSession,
  playerId: string,
  participationId: string,
): PendingGameOperation {
  return {
    kind: 'leave',
    communityId: session.community_id,
    gameId: session.game.game_id,
    participationId,
    body: {
      player_id: playerId,
      request_id: crypto.randomUUID(),
      expected_state_version: session.game.state_version,
      participation_id: participationId,
    },
  };
}

// 各玩法的合法动作与提交动作是同一组字段模型，逐字段比对即可统一判定合法性，
// 不需要按玩法各写一份比较规则；字段值都是原始值，用 === 比较即可。
function isLegalAction(candidate: object, action: object) {
  const legal = candidate as Record<string, unknown>;
  const fields = Object.entries(action as Record<string, unknown>);
  return (
    fields.length === Object.keys(legal).length &&
    fields.every(([key, value]) => legal[key] === value)
  );
}

export function actionOperation(
  session: GameSession,
  view: GameView,
  playerId: string,
  action: GameAction,
): PendingGameOperation | null {
  const opportunity = view.opportunities[0];
  if (
    !opportunity ||
    session.conversation.status !== 'active' ||
    session.game.status !== 'running' ||
    view.state_version !== session.game.state_version ||
    opportunity.participation_id !== session.self_participation_id
  )
    return null;
  const legalActions: readonly object[] = opportunity.legal_actions;
  if (!legalActions.some((candidate) => isLegalAction(candidate, action))) return null;
  return {
    kind: 'action',
    communityId: session.community_id,
    gameId: session.game.game_id,
    participationId: opportunity.participation_id,
    body: {
      player_id: playerId,
      request_id: crypto.randomUUID(),
      opportunity_id: opportunity.opportunity_id,
      expected_state_version: opportunity.expected_state_version,
      action,
    },
  };
}
