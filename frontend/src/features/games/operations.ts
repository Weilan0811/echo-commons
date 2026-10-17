import type { GameLifecycleKind, GameSession, GameView, PendingGameOperation } from '@/api/games';
import type { SchemaOf } from '@/api/http';

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
      return { ...common, kind, body: { ...body, seat_id: seatId } };
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
        body: { ...body, expected_conversation_version: session.conversation.state_version },
      };
    case 'start':
      return { ...common, kind, body };
  }
}

export function actionOperation(
  session: GameSession,
  view: GameView,
  playerId: string,
  action: SchemaOf<'PlaceStoneAction'>,
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
  if (
    !opportunity.legal_actions.some(
      (legal) => legal.type === action.type && legal.x === action.x && legal.y === action.y,
    )
  )
    return null;
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
