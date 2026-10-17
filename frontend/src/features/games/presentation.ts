import type { GameSession, GameType } from '@/api/games';
import type { PublicDisplay } from '@/api/directory';
import { senderKey } from '@/lib/groupMessages';

export const characterParticipationLabels = {
  memory_preparing: '记忆准备中',
  memory_failed: '记忆准备失败',
  unavailable: '当前不可参与',
  already_seated: '已经入座',
};

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
    (reference ? reference.replace(/^(player|character):/, '') : '等待入座')
  );
}

export function roomTitle(session: GameSession, members: readonly PublicDisplay[]) {
  return `${playerName(session.game.creator_ref, members)}的棋局`;
}
