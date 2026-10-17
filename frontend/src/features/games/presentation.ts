import type { GameSession, GameType } from '@/api/games';
import type { PublicDisplay } from '@/api/directory';
import { senderKey } from '@/lib/groupMessages';

export function playerCountLabel(type: GameType): string {
  const minimum = Math.min(...type.rulesets.map((ruleset) => ruleset.min_players));
  const maximum = Math.max(...type.rulesets.map((ruleset) => ruleset.max_players));
  return minimum === maximum ? `${minimum} 人` : `${minimum}～${maximum} 人`;
}

export function memberFor(reference: string | undefined, members: readonly PublicDisplay[]) {
  return members.find((member) => senderKey(member.actor) === reference);
}

export function playerName(reference: string | undefined, members: readonly PublicDisplay[]) {
  return (
    memberFor(reference, members)?.display_name ??
    (reference ? reference.replace(/^player:/, '') : '等待入座')
  );
}

export function roomTitle(session: GameSession, members: readonly PublicDisplay[]) {
  return `${playerName(session.game.creator_ref, members)}的棋局`;
}
