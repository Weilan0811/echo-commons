import { describe, expect, it } from 'vitest';
import { actionDestination } from './interaction';
import { FINISH_CELL, SEAT_ORDER, cellCenter, planeSpot, waitingSpot } from './coordinates';

describe('飞行棋合法动作的落点提示', () => {
  const planes = SEAT_ORDER.map((seat_id, index) => ({ seat_id, plane_id: 1, step: index * 4 }));

  it('同号飞机分别按自己的席位计算前进和跳格位置', () => {
    SEAT_ORDER.forEach((seat, index) => {
      expect(actionDestination(planes, seat, { type: 'move_plane', plane_id: 1 }, 3)).toEqual(
        planeSpot(seat, 1, index * 4 + 3),
      );
      expect(actionDestination(planes, seat, { type: 'jump_four', plane_id: 1 }, 4)).toEqual(
        planeSpot(seat, 1, index * 4 + 4),
      );
    });
  });

  it('其他席位的同号飞机无法代替自己的机场棋子生成提示', () => {
    expect(
      actionDestination(
        [
          { seat_id: 'red', plane_id: 1, step: 20 },
          { seat_id: 'yellow', plane_id: 1, step: null },
        ],
        'yellow',
        { type: 'move_plane', plane_id: 1 },
        2,
      ),
    ).toBeNull();
  });

  it('四家的起飞、飞越和反弹提示分别落在对应位置', () => {
    SEAT_ORDER.forEach((seat) => {
      expect(actionDestination(planes, seat, { type: 'take_off', plane_id: 1 }, 6)).toEqual(
        waitingSpot(seat),
      );
      expect(actionDestination(planes, seat, { type: 'fly_shortcut', plane_id: 1 }, 4)).toEqual(
        planeSpot(seat, 1, 28),
      );
      expect(
        actionDestination(
          [{ seat_id: seat, plane_id: 1, step: 53 }],
          seat,
          { type: 'move_plane', plane_id: 1 },
          5,
        ),
      ).toEqual(planeSpot(seat, 1, 52));
      expect(
        actionDestination(
          [{ seat_id: seat, plane_id: 1, step: 54 }],
          seat,
          { type: 'move_plane', plane_id: 1 },
          1,
        ),
      ).toEqual(cellCenter(FINISH_CELL));
    });
  });

  it('掷骰、结束移动和惩罚没有前进落点', () => {
    expect(actionDestination(planes, 'red', { type: 'roll_dice' }, null)).toBeNull();
    expect(actionDestination(planes, 'red', { type: 'end_move' }, 4)).toBeNull();
    expect(actionDestination(planes, 'red', { type: 'return_penalty', plane_id: 1 }, 6)).toBeNull();
  });
});
