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
    '2～4 人轮流掷骰：掷到 6 可以起飞一枚飞机到待飞位，或让一枚在场飞机前进 6 格，并追加一次掷骰。踏上本色普通格可以跳四格，虚线格可以飞越 12 格。到达格上的对方飞机全部返回机场。同一回合连续三次 6 时，选择一枚在场飞机返回机场并结束回合。到达归航入口后进入本色通道；点数超过终点会反弹回退，恰好到达终点才算完成。四枚飞机全部完成者获胜。',
  createInput: (): GameCreationInput => ({
    game_type: 'aeroplane',
    ruleset_id: 'aeroplane.traditional',
    ruleset_version: 1,
    initial_seat_id: 'red',
    config: {},
  }),
};
