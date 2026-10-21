import { useId, type KeyboardEvent } from 'react';
import type { GameAction } from '@/api/games';
import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';
import {
  BASE_ORIGIN,
  BASE_SIZE,
  BOARD_VIEW,
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
  waitingSpot,
  type Cell,
  type SeatId,
} from './coordinates';

// 格子在自家跑道与环线上的落位偏移，取小值让相邻格之间留出接缝。
const CELL_INSET = 3;
const CELL_SIZE = TILE - CELL_INSET * 2;
const CELL_RADIUS = 12;
const PLANE_SIZE = 52;
const HINT_RADIUS = 25;
// 机场平台与四个停机位收在 4×4 区域内，停机位半径与平台边距相配合，
// 保证四个停机位都落在平台内。
const BASE_INSET = 40;
const SLOT_RADIUS = 24;
// 待飞区（机场出口）圆台叠在平台朝向起飞格的角上。
const GATE_RADIUS = 24;
// 捷径只作方向提示：一条本色虚线叠在浅色导轨上，配一枚本色飞机剪影，指向飞越方向。
const SHORTCUT_MARK = 0.5;
// 飞机剪影机头朝上（-y），使用时按飞越方向再转 90° 对齐。
const SHORTCUT_PLANE =
  'M0 -20L4 -6L17 4L17 9L4 4L3 13L8 18L8 21L0 19L-8 21L-8 18L-3 13L-4 4L-17 9L-17 4L-4 -6Z';
const DICE_DIR = '/assets/games/activity/aeroplane/ui';
const PLANE_DIR = '/assets/games/activity/aeroplane/pieces';

// 起飞处箭头指向顺时针行进方向，提示棋子上跑道后的走向。
const TAKEOFF_ARROW: Record<SeatId, readonly [number, number]> = {
  red: [1, 0],
  yellow: [0, 1],
  blue: [-1, 0],
  green: [0, -1],
};

// 起飞格标记按席位反查：52 格环上每家的起飞格都是本家颜色，标记仍然按格号定位。
const TAKEOFF_MARK: readonly (SeatId | undefined)[] = RING_CELLS.map((_, index) =>
  SEAT_ORDER.find((seat) => TAKEOFF_CELL[seat] === index),
);

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
        hints.push({ ...waitingSpot(viewer), seat: viewer });
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
        const spot = planeSpot(viewer, action.plane_id, SHORTCUT_LANDING_STEP[viewer]);
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
          const x = ORIGIN + col * TILE + BASE_INSET;
          const y = ORIGIN + row * TILE + BASE_INSET;
          const size = BASE_SIZE * TILE - BASE_INSET * 2;
          return (
            <g key={`base-${seat}`}>
              <rect
                x={x}
                y={y}
                width={size}
                height={size}
                rx={22}
                fill={fill.cell}
                opacity=".82"
              />
              <rect
                x={x}
                y={y}
                width={size}
                height={size}
                rx={22}
                fill="none"
                stroke={fill.deep}
                strokeWidth="3"
                opacity=".5"
              />
              {[1, 2, 3, 4].map((planeId) => {
                const slot = baseSlot(seat, planeId);
                return (
                  <circle
                    key={`slot-${planeId}`}
                    cx={slot.x}
                    cy={slot.y}
                    r={SLOT_RADIUS}
                    fill="#fffdf4"
                    opacity=".95"
                    stroke={fill.deep}
                    strokeWidth="2"
                  />
                );
              })}
              {(() => {
                // 机场出口的待飞位：圆台叠在平台朝向起飞格的角上，小箭头指向起飞格。
                const gate = waitingSpot(seat);
                const target = ringCellCenter(TAKEOFF_CELL[seat]);
                const dx = target.x - gate.x;
                const dy = target.y - gate.y;
                const len = Math.hypot(dx, dy) || 1;
                const ux = dx / len;
                const uy = dy / len;
                return (
                  <g>
                    <circle
                      cx={gate.x}
                      cy={gate.y}
                      r={GATE_RADIUS}
                      fill={fill.soft}
                      stroke={fill.deep}
                      strokeWidth="2.5"
                    />
                    <path
                      d={`M${gate.x + ux * 7 - uy * 6} ${gate.y + uy * 7 + ux * 6}L${gate.x + ux * 16} ${gate.y + uy * 16}L${gate.x + ux * 7 + uy * 6} ${gate.y + uy * 7 - ux * 6}`}
                      fill="none"
                      stroke={fill.deep}
                      strokeWidth="3.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </g>
                );
              })()}
            </g>
          );
        })}

        {RING_CELLS.map((cell, index) => {
          const seat = seatOfCell(index);
          const fill = SEAT_FILL[seat];
          const markSeat = TAKEOFF_MARK[index];
          const center = cellCenter(cell);
          return (
            <g key={`ring-${index}`}>
              <rect
                {...tileOf(cell)}
                fill={markSeat ? fill.deep : fill.cell}
                stroke={fill.deep}
                strokeWidth="1.5"
              />
              {markSeat
                ? (() => {
                    const [dx, dy] = TAKEOFF_ARROW[markSeat];
                    const px = -dy;
                    const py = dx;
                    return (
                      <path
                        d={`M${center.x - dx * 4 + px * 11} ${center.y - dy * 4 + py * 11}L${center.x + dx * 15} ${center.y + dy * 15}L${center.x - dx * 4 - px * 11} ${center.y - dy * 4 - py * 11}`}
                        fill="none"
                        stroke={SEAT_FILL[markSeat].soft}
                        strokeWidth="6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    );
                  })()
                : null}
            </g>
          );
        })}

        {SEAT_ORDER.map((seat) => {
          const fill = SEAT_FILL[seat];
          return HOMESTRETCH[seat].map((cell, index) => {
            const center = cellCenter(cell);
            const last = index === HOMESTRETCH[seat].length - 1;
            return (
              <g key={`stretch-${seat}-${index}`}>
                <rect {...tileOf(cell)} fill={fill.deep} stroke={fill.cell} strokeWidth="1.5" />
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
          const from = ringCellCenter(ringCellIndex(seat, SHORTCUT_STEP[seat]));
          const to = ringCellCenter(ringCellIndex(seat, SHORTCUT_LANDING_STEP[seat]));
          const angle = (Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI;
          const deep = SEAT_FILL[seat].deep;
          const path = `M${from.x} ${from.y}L${to.x} ${to.y}`;
          return (
            <g key={`shortcut-${seat}`}>
              <path
                d={path}
                fill="none"
                stroke="#fffdf4"
                strokeWidth="4.5"
                strokeLinecap="round"
                opacity=".42"
              />
              <path
                d={path}
                fill="none"
                stroke={deep}
                strokeWidth="2.4"
                strokeDasharray="9 13"
                strokeLinecap="round"
                opacity=".85"
              />
              {(() => {
                const x = from.x + (to.x - from.x) * SHORTCUT_MARK;
                const y = from.y + (to.y - from.y) * SHORTCUT_MARK;
                return (
                  <path
                    d={SHORTCUT_PLANE}
                    fill={deep}
                    stroke="#fffdf4"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                    opacity=".9"
                    transform={`translate(${x} ${y}) rotate(${angle + 90})`}
                  />
                );
              })()}
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
