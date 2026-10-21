import type { GameCreationInput } from '@/api/games';
import { seatStyle } from '@/features/games/presentation';

export function AeroplaneCover() {
  return (
    <div className="game-mini-planes">
      {['red', 'yellow', 'blue', 'green'].map((seatId) => (
        <span
          key={seatId}
          className="game-mini-plane"
          style={{ background: seatStyle('aeroplane', seatId).tone }}
        />
      ))}
    </div>
  );
}

export const aeroplanePresentation = {
  Cover: AeroplaneCover,
  description: '四色机场与外圈 52 格，四枚棋子先全部归航者获胜。',
  rules:
    '2～4 人轮流掷骰：掷到 6 可以起飞一枚棋子到机场旁的待飞位，或让一枚在场棋子（含待飞位）前进 6 格并追加一次掷骰。踏上本色格跳四格，踏上本色虚线格沿虚线飞越 12 格到前方本色格。到达格上的对方棋子全部返回机场。同一回合连续三次 6 时，由该玩家选一枚在场棋子返回机场并结束回合。棋子走完外圈进入本色归航道共 6 格，超过终点按「112 减目标步数」反弹，四枚棋子都到终点者获胜。',
  createInput: (): GameCreationInput => ({
    game_type: 'aeroplane',
    ruleset_id: 'aeroplane.traditional',
    ruleset_version: 1,
    initial_seat_id: 'red',
    config: {},
  }),
};
