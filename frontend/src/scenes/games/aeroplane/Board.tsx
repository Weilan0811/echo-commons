import { type KeyboardEvent } from 'react';
import type { GameAction } from '@/api/games';
import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';
import { BOARD_VIEW, SEAT_FILL, SEAT_ORDER, planeSpot, type SeatId } from './coordinates';
import { actionDestination } from './interaction';
import { BoardArtwork } from './BoardArtwork';

const PLANE_SIZE = 46;
const HINT_RADIUS = 25;
const DICE_DIR = '/assets/games/activity/aeroplane/ui';
const PLANE_DIR = '/assets/games/activity/aeroplane/pieces';

// 同格叠子时按 plane_id 顺序错开，避免完全重合。
const STACK_OFFSETS = [
  { x: -13, y: -13 },
  { x: 13, y: -13 },
  { x: -13, y: 13 },
  { x: 13, y: 13 },
] as const;

export function Board(props: BoardProps) {
  const view = props.view;
  const { onAction, pending = false } = props;
  // 视图联合按 game_type 收窄后，本组件只处理飞行棋视图。
  if (view && view.game_type !== 'aeroplane') return null;
  const state = view?.state ?? null;
  const opportunity = view?.opportunities[0];
  const legal: readonly GameAction[] = opportunity?.legal_actions ?? [];
  const canAct = !!onAction && !!opportunity && !pending;
  const viewer = SEAT_ORDER.find((seat) => seat === view?.viewer_seat_id) ?? null;
  const currentSeat = SEAT_ORDER.find((seat) => seat === state?.current_seat_id) ?? null;
  const dice = state?.dice ?? null;
  const phase = state?.phase ?? 'awaiting_roll';

  // 每个带 plane_id 的合法动作都表示「点这枚棋子即可执行」，收窄后按棋子索引。
  const planeActions = new Map<number, GameAction>();
  if (canAct) {
    for (const action of legal) {
      if ('plane_id' in action) planeActions.set(action.plane_id, action);
    }
  }
  const rollAction = legal.find((action) => action.type === 'roll_dice');
  const flyAction = legal.find((action) => action.type === 'fly_shortcut');
  const jumpAction = legal.find((action) => action.type === 'jump_four');
  const endAction = legal.find((action) => action.type === 'end_move');

  const planes = state?.planes ?? [];
  // 先按落位分组再编号，保证同格叠子每次都按 plane_id 稳定错开。
  const seatCount = new Map<string, number>();
  const positions = [...planes]
    .sort(
      (a, b) =>
        SEAT_ORDER.indexOf(a.seat_id) - SEAT_ORDER.indexOf(b.seat_id) || a.plane_id - b.plane_id,
    )
    .map((plane) => {
      const spot = planeSpot(plane.seat_id, plane.plane_id, plane.step ?? null);
      const key = `${spot.x.toFixed(1)}:${spot.y.toFixed(1)}`;
      const index = seatCount.get(key) ?? 0;
      seatCount.set(key, index + 1);
      return { plane, spot, key, index };
    });
  const placed = positions.map(({ plane, spot, key, index }) => {
    const stacked = seatCount.get(key)! > 1;
    const offset = stacked ? STACK_OFFSETS[index]! : { x: 0, y: 0 };
    return { plane, spot, offset, size: stacked ? 30 : PLANE_SIZE };
  });

  // 合法动作的落点提示：前进给出反弹后的落点，连锁给出跳越后的落点。
  const hints: { x: number; y: number; seat: SeatId }[] = [];
  if (canAct && viewer) {
    for (const action of legal) {
      const spot = actionDestination(planes, viewer, action, dice);
      if (spot && !hints.some((item) => item.x === spot.x && item.y === spot.y))
        hints.push({ ...spot, seat: viewer });
    }
  }

  const act = (action: GameAction) => {
    if (canAct) onAction?.(action);
  };
  const key = (event: KeyboardEvent, action: GameAction) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      act(action);
    }
  };

  const seatMark = currentSeat ? seatStyle('aeroplane', currentSeat) : null;
  let hint: string;
  if (!state) hint = '等待对局开始';
  else if (phase === 'finished') hint = '本局已结束';
  else if (!canAct) hint = `等${seatMark?.label ?? '对手'}行动`;
  else if (phase === 'awaiting_roll') hint = '掷骰，开始这一回合';
  else if (phase === 'awaiting_action')
    hint =
      dice === 6
        ? '点击机场里的飞机进入待飞位，或点击棋盘上的飞机前进'
        : '点击棋盘或待飞位上的飞机前进';
  else if (phase === 'awaiting_chain') hint = '选择跳四格或沿虚线飞越，也可以结束移动';
  else hint = '点击一枚在棋盘上的飞机返回机场';

  const buttons: { action: GameAction; label: string; primary?: boolean }[] = [];
  if (canAct) {
    if (rollAction) buttons.push({ action: rollAction, label: '掷骰子', primary: true });
    if (flyAction) buttons.push({ action: flyAction, label: '沿虚线飞越', primary: true });
    if (jumpAction) buttons.push({ action: jumpAction, label: '跳四格', primary: true });
    if (endAction) buttons.push({ action: endAction, label: '结束移动' });
  }

  return (
    <div className="aeroplane-board-wrap">
      <svg
        viewBox={`0 0 ${BOARD_VIEW} ${BOARD_VIEW}`}
        className="aeroplane-board"
        role={canAct ? 'group' : 'img'}
        aria-label={`飞行棋棋盘，${gamePhaseLabel('aeroplane', phase)}`}
      >
        <BoardArtwork activeShortcut={canAct && flyAction ? viewer : null} />

        {hints.map((hintSpot, index) => (
          <circle
            key={`hint-${index}`}
            className="aeroplane-hint"
            cx={hintSpot.x}
            cy={hintSpot.y}
            r={HINT_RADIUS}
            fill={SEAT_FILL[hintSpot.seat].soft}
            stroke={SEAT_FILL[hintSpot.seat].deep}
            strokeWidth="3"
            strokeDasharray="7 6"
          />
        ))}

        {placed.map(({ plane, spot, offset, size }) => {
          const cx = spot.x + offset.x;
          const cy = spot.y + offset.y;
          const action = planeActions.get(plane.plane_id);
          const clickable = action !== undefined && plane.seat_id === viewer;
          const label = `${seatStyle('aeroplane', plane.seat_id).label}第 ${plane.plane_id} 号飞机${spot.home ? '，已完成' : ''}`;
          return (
            <g
              key={`${plane.seat_id}-${plane.plane_id}`}
              className={clickable ? 'aeroplane-plane aeroplane-plane-active' : 'aeroplane-plane'}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
              aria-label={clickable ? `${label}，可行动` : label}
              onClick={clickable ? () => act(action) : undefined}
              onKeyDown={clickable ? (event) => key(event, action) : undefined}
            >
              <title>{label}</title>
              {spot.home ? (
                <circle
                  cx={cx}
                  cy={cy}
                  r={27}
                  fill="none"
                  stroke="#f2cd7a"
                  strokeWidth="3"
                  opacity=".9"
                />
              ) : null}
              {clickable ? (
                <circle
                  cx={cx}
                  cy={cy}
                  r={size / 2 + 2}
                  fill={SEAT_FILL[plane.seat_id].soft}
                  opacity=".45"
                  stroke={SEAT_FILL[plane.seat_id].deep}
                  strokeWidth="3"
                />
              ) : null}
              <image
                href={`${PLANE_DIR}/plane_${plane.seat_id}.svg`}
                x={cx - size / 2}
                y={cy - size / 2}
                width={size}
                height={size}
                opacity={spot.home ? 0.5 : 1}
              />
              <text
                x={cx + size / 2 - 4}
                y={cy + size / 2 - 1}
                textAnchor="middle"
                fontSize={size > 30 ? 14 : 11}
                fontWeight="700"
                fill="#fffdf4"
                stroke={SEAT_FILL[plane.seat_id].deep}
                strokeWidth="3"
                paintOrder="stroke"
                pointerEvents="none"
              >
                {spot.home ? '✓' : plane.plane_id}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="aeroplane-hud">
        <div className="aeroplane-hud-status">
          <img
            className="aeroplane-dice"
            src={dice ? `${DICE_DIR}/dice_face_${dice}.svg` : `${DICE_DIR}/dice_face_base.svg`}
            alt={dice ? `骰子 ${dice}` : '尚未掷骰'}
          />
          <div className="aeroplane-hud-copy">
            <p className="aeroplane-hud-turn">
              {seatMark ? (
                <>
                  <i className="game-stone-dot" style={{ background: seatMark.tone }} />
                  {seatMark.label}
                  <span>{gamePhaseLabel('aeroplane', phase)}</span>
                </>
              ) : (
                <span>{gamePhaseLabel('aeroplane', phase)}</span>
              )}
            </p>
            <p className="aeroplane-hud-hint">
              {hint}
              {state && state.consecutive_sixes > 0 && phase !== 'finished' ? (
                <span className="aeroplane-hud-warn">已连掷 {state.consecutive_sixes} 次六</span>
              ) : null}
            </p>
          </div>
        </div>
        {canAct &&
        (phase === 'awaiting_action' || phase === 'awaiting_penalty') &&
        placed.some(
          ({ plane, size }) =>
            size < PLANE_SIZE && plane.seat_id === viewer && planeActions.has(plane.plane_id),
        ) ? (
          <div className="aeroplane-stack-actions" aria-label="选择同格飞机">
            <span>同格飞机</span>
            {placed
              .filter(
                ({ plane, size }) =>
                  size < PLANE_SIZE && plane.seat_id === viewer && planeActions.has(plane.plane_id),
              )
              .map(({ plane }) => {
                const action = planeActions.get(plane.plane_id)!;
                return (
                  <button
                    key={plane.plane_id}
                    type="button"
                    className="game-button game-button-quiet"
                    onClick={() => act(action)}
                  >
                    {action.type === 'return_penalty' ? '返回' : '移动'} {plane.plane_id} 号
                  </button>
                );
              })}
          </div>
        ) : null}
        {buttons.length ? (
          <div className="aeroplane-hud-actions">
            {buttons.map((item) => (
              <button
                key={item.label}
                type="button"
                className={`game-button ${item.primary ? 'game-button-primary' : 'game-button-quiet'}`}
                onClick={() => act(item.action)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
        {state?.result ? (
          <div className="aeroplane-hud-result">
            <img src={`${DICE_DIR}/winner_badge.svg`} alt="" width="30" height="30" />
            <span>{seatStyle('aeroplane', state.result.winner_seat_id).label}获胜</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
