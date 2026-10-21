import type { GameAction } from '@/api/games';
import {
  FINISH_CELL,
  HOME_STEP,
  SHORTCUT_LANDING_STEP,
  advanceStep,
  cellCenter,
  planeSpot,
  waitingSpot,
  type SeatId,
} from './coordinates';

type Plane = { seat_id: SeatId; plane_id: number; step?: number | null };

// 提示只计算已由后端允许的动作；每家独立编号，必须同时匹配席位和编号。
export function actionDestination(
  planes: readonly Plane[],
  viewer: SeatId,
  action: GameAction,
  dice: number | null,
) {
  if (action.type === 'take_off') return waitingSpot(viewer);
  if (action.type === 'fly_shortcut')
    return planeSpot(viewer, action.plane_id, SHORTCUT_LANDING_STEP[viewer]);
  if (action.type !== 'move_plane' && action.type !== 'jump_four') return null;
  const plane = planes.find((item) => item.seat_id === viewer && item.plane_id === action.plane_id);
  if (plane?.step == null || (action.type === 'move_plane' && dice === null)) return null;
  const step =
    action.type === 'jump_four' ? plane.step + 4 : advanceStep(plane.step, dice!);
  return step === HOME_STEP
    ? cellCenter(FINISH_CELL)
    : planeSpot(viewer, plane.plane_id, step);
}
