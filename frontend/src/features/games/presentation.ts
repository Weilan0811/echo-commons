import type { GameAction, GameSession, GameType, GameView } from '@/api/games';
import type { PublicDisplay } from '@/api/directory';
import { senderKey } from '@/lib/groupMessages';

// 所有玩法的棋盘共用同一组属性，各自的棋盘内部再按 game_type 收窄视图。
export type BoardProps = {
  view: GameView | null;
  onAction?: ((action: GameAction) => void) | undefined;
  pending?: boolean;
};

export const characterParticipationLabels = {
  memory_preparing: '记忆准备中',
  memory_failed: '记忆准备失败',
  unavailable: '当前不可参与',
  already_seated: '已经入座',
};

const gameTitles: Record<string, string> = {
  gomoku: '五子棋',
  aeroplane: '飞行棋',
  kingdomino: 'Kingdomino',
};

const rulesetDisplayNames: Record<string, string> = {
  'gomoku.freestyle': '自由规则',
  'aeroplane.traditional': '传统玩法',
  'kingdomino.classic': '经典规则',
};

// 席位色是棋盘上的物理色（棋子、机场、王国棋子），不是界面主题色，
// 因此在这里按玩法统一登记，界面只负责把它画成席位圆点。
const seatStyles: Record<string, Record<string, { label: string; tone: string }>> = {
  gomoku: {
    black: { label: '执黑 · 先行', tone: 'radial-gradient(circle at 30% 25%, #666267, #19191e 75%)' },
    white: { label: '执白', tone: 'radial-gradient(circle at 30% 25%, #fffdf1, #cdc6b6 90%)' },
  },
  aeroplane: {
    red: { label: '红方', tone: 'radial-gradient(circle at 30% 25%, #f19a8c, #c9483d 78%)' },
    yellow: { label: '黄方', tone: 'radial-gradient(circle at 30% 25%, #f7d98a, #d99a1f 78%)' },
    blue: { label: '蓝方', tone: 'radial-gradient(circle at 30% 25%, #a4c9f5, #3f74c4 78%)' },
    green: { label: '绿方', tone: 'radial-gradient(circle at 30% 25%, #a9dfb0, #377f5b 78%)' },
  },
  kingdomino: {
    pink: { label: '粉方', tone: 'radial-gradient(circle at 30% 25%, #f2b3c6, #c9557e 78%)' },
    yellow: { label: '黄方', tone: 'radial-gradient(circle at 30% 25%, #f7d98a, #d99a1f 78%)' },
    green: { label: '绿方', tone: 'radial-gradient(circle at 30% 25%, #a9dfb0, #377f5b 78%)' },
    blue: { label: '蓝方', tone: 'radial-gradient(circle at 30% 25%, #a4c9f5, #3f74c4 78%)' },
  },
};

const phaseLabels: Record<string, Record<string, string>> = {
  aeroplane: {
    awaiting_roll: '等待掷骰',
    awaiting_action: '等待选择棋子',
    awaiting_chain: '等待追加行动',
    awaiting_penalty: '三次六返航',
    finished: '已结束',
  },
  kingdomino: {
    seeding: '放置国王',
    placing: '拼接地块',
    choosing: '挑选地块',
    finished: '已结算',
  },
};

export function gameTitle(gameType: string) {
  return gameTitles[gameType] ?? gameType;
}

export function gameEyebrow(gameType: string, rulesetId: string) {
  return `${gameTitle(gameType)} · ${rulesetDisplayNames[rulesetId] ?? rulesetId}`;
}

export function seatStyle(gameType: string, seatId: string) {
  return (
    seatStyles[gameType]?.[seatId] ?? { label: seatId, tone: 'var(--color-surface-overlay)' }
  );
}

export function gamePhaseLabel(gameType: string, phase: string) {
  return phaseLabels[gameType]?.[phase] ?? phase;
}

// 对局页页脚与棋盘占位共用的一句话局势摘要；没有视图时回落到传入的提示文本。
export function gameSummary(view: GameView | null, idleText: string) {
  if (!view) return idleText;
  switch (view.game_type) {
    case 'gomoku':
      return `${view.state.stones.length} 手落子`;
    case 'aeroplane':
      return view.state.dice
        ? `${gamePhaseLabel('aeroplane', view.state.phase)} · 骰 ${view.state.dice}`
        : gamePhaseLabel('aeroplane', view.state.phase);
    case 'kingdomino':
      return `${gamePhaseLabel('kingdomino', view.state.phase)} · 牌堆余 ${view.state.deck_remaining}`;
  }
}

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
