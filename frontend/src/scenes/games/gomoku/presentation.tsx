import type { GameCreationInput } from '@/api/games';

export function GomokuCover() {
  return (
    <div className="game-mini-board">
      <span className="game-mini-black" />
      <span className="game-mini-white" />
    </div>
  );
}

export const gomokuPresentation = {
  Cover: GomokuCover,
  description: '15 × 15 棋盘，连续五子及以上获胜。',
  rules:
    '黑方先行，双方在空交点轮流落子。横向、纵向或斜向连续五枚及以上获胜，无禁手。棋盘填满且无人获胜时为和局。',
  createInput: (): GameCreationInput => ({
    game_type: 'gomoku',
    ruleset_id: 'gomoku.freestyle',
    ruleset_version: 1,
    initial_seat_id: 'black',
    config: {},
  }),
};
