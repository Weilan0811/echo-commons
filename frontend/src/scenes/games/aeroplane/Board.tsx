import { useId, type KeyboardEvent } from 'react';
import type { GameAction } from '@/api/games';
import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';
import {
  BASE_ORIGIN,
  BASE_SIZE,
  BOARD_VIEW,
  DIAGONAL_SEAT,
  HOMESTRETCH,
  ORIGIN,
  RING_CELLS,
  SEAT_FILL,
  SEAT_ORDER,
  SHORTCUT_LANDING_STEP,
  SHORTCUT_STEP,
  TAKEOFF_CELL,
  TILE,
  advanceStep,
  baseSlot,
  cellCenter,
  planeSpot,
  ringCellCenter,
  ringCellIndex,
  seatOfCell,
  type Cell,
  type SeatId,
} from './coordinates';

// 格子在自家跑道与环线上的落位偏移，取小值让相邻格之间留出接缝。
const CELL_INSET = 3;
const CELL_SIZE = TILE - CELL_INSET * 2;
const CELL_RADIUS = 12;
const PLANE_SIZE = 52;
const HINT_RADIUS = 25;
const DICE_DIR = '/assets/games/activity/aeroplane/ui';
const PLANE_DIR = '/assets/games/activity/aeroplane/pieces';

// 起飞处指向中央的箭头方向，与自家归航道一致。
const TAKEOFF_ARROW: Record<SeatId, readonly [number, number]> = {
  red: [0, 1],
  yellow: [-1, 0],
  blue: [0, -1],
  green: [1, 0],
};

// 同格叠子时按 plane_id 顺序错开，避免完全重合。
const STACK_OFFSETS = [
  { x: 0, y: 0 },
  { x: -13, y: -11 },
  { x: 13, y: -11 },
  { x: 0, y: 13 },
] as const;

function tileOf(cell: Cell) {
  return {
    x: ORIGIN + cell[0] * TILE + CELL_INSET,
    y: ORIGIN + cell[1] * TILE + CELL_INSET,
    width: CELL_SIZE,
    height: CELL_SIZE,
    rx: CELL_RADIUS,
  };
}

// 棋盘按规则几何程序绘制：外圈 52 格、四角机场、四段归航道与中央终点。
// 前端只负责把几何画出来，格号与 step 的换算全部来自 coordinates。
export function Board(props: BoardProps) {
  const view = props.view;
  const { onAction, pending = false } = props;
  const id = useId().replace(/:/g, '');
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
  const placed = planes.map((plane) => {
    const spot = planeSpot(plane.seat_id, plane.plane_id, plane.step ?? null);
    const key = `${spot.x.toFixed(1)}:${spot.y.toFixed(1)}`;
    const index = seatCount.get(key) ?? 0;
    seatCount.set(key, index + 1);
    return { plane, spot, offset: STACK_OFFSETS[Math.min(index, STACK_OFFSETS.length - 1)]! };
  });

  // 合法动作的落点提示：前进给出反弹后的落点，连锁给出跳越后的落点。
  const hints: { x: number; y: number; seat: SeatId }[] = [];
  if (canAct && viewer) {
    for (const action of legal) {
      if (action.type === 'take_off') {
        hints.push({ ...ringCellCenter(TAKEOFF_CELL[viewer]), seat: viewer });
      } else if (action.type === 'move_plane' && dice !== null) {
        const plane = planes.find((item) => item.plane_id === action.plane_id);
        if (plane?.step != null) {
          const spot = planeSpot(viewer, action.plane_id, advanceStep(plane.step, dice));
          hints.push({ x: spot.x, y: spot.y, seat: viewer });
        }
      } else if (action.type === 'jump_four') {
        const plane = planes.find((item) => item.plane_id === action.plane_id);
        if (plane?.step != null) {
          const spot = planeSpot(viewer, action.plane_id, plane.step + 4);
          hints.push({ x: spot.x, y: spot.y, seat: viewer });
        }
      } else if (action.type === 'fly_shortcut') {
        const spot = planeSpot(viewer, action.plane_id, SHORTCUT_LANDING_STEP);
        hints.push({ x: spot.x, y: spot.y, seat: viewer });
      }
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
      dice === 6 ? '点击机场里的飞机起飞，或点击棋盘上的飞机前进' : '点击一枚在棋盘上的飞机前进';
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
        role="img"
        aria-label={`飞行棋棋盘，${gamePhaseLabel('aeroplane', phase)}`}
      >
        <defs>
          <linearGradient id={`${id}-edge`} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="var(--board-edge-light)" />
            <stop offset="1" stopColor="var(--board-edge)" />
          </linearGradient>
          <linearGradient id={`${id}-wood`} x1="0" y1="0" x2=".7" y2="1">
            <stop stopColor="var(--board-light)" />
            <stop offset=".55" stopColor="var(--board-base)" />
            <stop offset="1" stopColor="var(--board-shade)" />
          </linearGradient>
          <pattern id={`${id}-grain`} width="83" height="17" patternUnits="userSpaceOnUse">
            <path
              d="M0 3Q22 0 43 3T83 3M0 12Q35 16 83 11"
              fill="none"
              stroke="var(--board-grain)"
              strokeWidth=".5"
              opacity=".3"
            />
          </pattern>
        </defs>
        <rect x="4" y="4" width="992" height="992" rx="42" fill={`url(#${id}-edge)`} />
        <rect
          x="16"
          y="16"
          width="968"
          height="968"
          rx="34"
          fill={`url(#${id}-wood)`}
          stroke="var(--board-rim)"
        />
        <rect x="17" y="17" width="966" height="966" rx="33" fill={`url(#${id}-grain)`} />

        {SEAT_ORDER.map((seat) => {
          const fill = SEAT_FILL[seat];
          const [col, row] = BASE_ORIGIN[seat];
          const x = ORIGIN + col * TILE;
          const y = ORIGIN + row * TILE;
          const size = BASE_SIZE * TILE;
          return (
            <g key={`base-${seat}`}>
              <rect
                x={x + 6}
                y={y + 6}
                width={size - 12}
                height={size - 12}
                rx={30}
                fill={fill.soft}
                opacity=".5"
              />
              <rect
                x={x + 6}
                y={y + 6}
                width={size - 12}
                height={size - 12}
                rx={30}
                fill="none"
                stroke={fill.deep}
                strokeWidth="2.5"
                strokeDasharray="12 9"
                opacity=".7"
              />
              {[1, 2, 3, 4].map((planeId) => {
                const slot = baseSlot(seat, planeId);
                return (
                  <circle
                    key={`slot-${planeId}`}
                    cx={slot.x}
                    cy={slot.y}
                    r="42"
                    fill="#fffdf4"
                    opacity=".45"
                    stroke={fill.deep}
                    strokeWidth="2"
                    strokeDasharray="7 7"
                  />
                );
              })}
            </g>
          );
        })}

        {RING_CELLS.map((cell, index) => {
          const seat = seatOfCell(index);
          const fill = SEAT_FILL[seat];
          const takeoff = index === TAKEOFF_CELL[seat];
          const center = cellCenter(cell);
          const [dx, dy] = TAKEOFF_ARROW[seat];
          const px = -dy;
          const py = dx;
          return (
            <g key={`ring-${index}`}>
              <rect
                {...tileOf(cell)}
                fill={takeoff ? fill.deep : fill.cell}
                stroke={fill.deep}
                strokeWidth="1.5"
              />
              {takeoff ? (
                <path
                  d={`M${center.x - dx * 4 + px * 11} ${center.y - dy * 4 + py * 11}L${center.x + dx * 15} ${center.y + dy * 15}L${center.x - dx * 4 - px * 11} ${center.y - dy * 4 - py * 11}`}
                  fill="none"
                  stroke={fill.soft}
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ) : null}
            </g>
          );
        })}

        {SEAT_ORDER.map((seat) => {
          const fill = SEAT_FILL[seat];
          const crossFill = SEAT_FILL[DIAGONAL_SEAT[seat]];
          return HOMESTRETCH[seat].map((cell, index) => {
            const center = cellCenter(cell);
            const last = index === HOMESTRETCH[seat].length - 1;
            return (
              <g key={`stretch-${seat}-${index}`}>
                <rect {...tileOf(cell)} fill={fill.deep} stroke={fill.cell} strokeWidth="1.5" />
                {index === 2 ? (
                  <rect
                    x={center.x - 14}
                    y={center.y - 14}
                    width="28"
                    height="28"
                    rx="6"
                    fill={crossFill.cell}
                    stroke="#fffdf4"
                    strokeWidth="2"
                    transform={`rotate(45 ${center.x} ${center.y})`}
                  />
                ) : null}
                {last ? (
                  <circle
                    cx={center.x}
                    cy={center.y}
                    r="20"
                    fill="none"
                    stroke="#f4d68f"
                    strokeWidth="3"
                    strokeDasharray="6 6"
                  />
                ) : null}
              </g>
            );
          });
        })}

        {(() => {
          const center = cellCenter([7, 7]);
          const arm = 28;
          return (
            <g>
              <rect
                x={center.x - 29}
                y={center.y - 29}
                width="58"
                height="58"
                rx="5"
                fill="var(--board-rim)"
                stroke="var(--board-line)"
                strokeWidth="2"
              />
              <path
                d={`M${center.x} ${center.y}L${center.x - arm} ${center.y - arm}L${center.x + arm} ${center.y - arm}Z`}
                fill={SEAT_FILL.red.cell}
              />
              <path
                d={`M${center.x} ${center.y}L${center.x + arm} ${center.y - arm}L${center.x + arm} ${center.y + arm}Z`}
                fill={SEAT_FILL.yellow.cell}
              />
              <path
                d={`M${center.x} ${center.y}L${center.x + arm} ${center.y + arm}L${center.x - arm} ${center.y + arm}Z`}
                fill={SEAT_FILL.blue.cell}
              />
              <path
                d={`M${center.x} ${center.y}L${center.x - arm} ${center.y + arm}L${center.x - arm} ${center.y - arm}Z`}
                fill={SEAT_FILL.green.cell}
              />
              <circle
                cx={center.x}
                cy={center.y}
                r="8"
                fill="#fffdf4"
                stroke="var(--board-line)"
                strokeWidth="2"
              />
            </g>
          );
        })()}

        {SEAT_ORDER.map((seat) => {
          const from = ringCellCenter(ringCellIndex(seat, SHORTCUT_STEP));
          const to = ringCellCenter(ringCellIndex(seat, SHORTCUT_LANDING_STEP));
          const angle = Math.atan2(to.y - from.y, to.x - from.x);
          const back = 34;
          const tip = { x: to.x - Math.cos(angle) * back, y: to.y - Math.sin(angle) * back };
          const deg = (angle * 180) / Math.PI;
          return (
            <g key={`shortcut-${seat}`} opacity=".5">
              <path
                d={`M${from.x} ${from.y}L${to.x} ${to.y}`}
                fill="none"
                stroke={SEAT_FILL[seat].deep}
                strokeWidth="3"
                strokeDasharray="14 10"
                strokeLinecap="round"
              />
              <path
                d={`M${tip.x} ${tip.y}L${tip.x - 18} ${tip.y - 9}L${tip.x - 18} ${tip.y + 9}Z`}
                fill={SEAT_FILL[seat].deep}
                transform={`rotate(${deg} ${tip.x} ${tip.y})`}
              />
            </g>
          );
        })}

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

        {placed.map(({ plane, spot, offset }) => {
          const cx = spot.x + offset.x;
          const cy = spot.y + offset.y;
          const action = planeActions.get(plane.plane_id);
          const clickable = action !== undefined && plane.seat_id === viewer;
          const label = `${seatStyle('aeroplane', plane.seat_id).label}第 ${plane.plane_id} 号飞机`;
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
                  r="27"
                  fill={SEAT_FILL[plane.seat_id].soft}
                  opacity=".45"
                  stroke={SEAT_FILL[plane.seat_id].deep}
                  strokeWidth="3"
                />
              ) : null}
              <image
                href={`${PLANE_DIR}/plane_${plane.seat_id}.svg`}
                x={cx - PLANE_SIZE / 2}
                y={cy - PLANE_SIZE / 2}
                width={PLANE_SIZE}
                height={PLANE_SIZE}
                opacity={spot.home ? 0.5 : 1}
              />
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
