import { useId, useState, type PointerEvent, type KeyboardEvent } from 'react';
import type { BoardProps } from '@/features/games/presentation';
import { BOARD_SIZE, GRID_ORIGIN, GRID_STEP, coordinateLabel, intersectionAt } from './coordinates';

export function Board(props: BoardProps) {
  const view = props.view;
  const { onAction, pending = false } = props;
  // 视图联合按 game_type 收窄后，本组件只处理五子棋视图。
  if (view && view.game_type !== 'gomoku') return null;
  const id = useId().replace(/:/g, '');
  const [preview, setPreview] = useState<{ x: number; y: number } | null>(null);
  const [touchPreview, setTouchPreview] = useState(false);
  const stones = view?.state.stones ?? [];
  const last = stones.at(-1);
  const opportunity = view?.opportunities[0];
  const canAct = !!onAction && !!opportunity && !pending;
  const legal = (point: { x: number; y: number }) =>
    opportunity?.legal_actions.some((action) => action.x === point.x && action.y === point.y) ??
    false;
  const pointFrom = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return intersectionAt(
      ((event.clientX - rect.left) * BOARD_SIZE) / rect.width,
      ((event.clientY - rect.top) * BOARD_SIZE) / rect.height,
    );
  };
  const submit = (point: { x: number; y: number }) => {
    if (!canAct || !legal(point)) return;
    onAction?.({ type: 'place_stone', ...point });
    setPreview(null);
    setTouchPreview(false);
  };
  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    if (!canAct) return;
    const selected = preview ?? { x: 7, y: 7 };
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      submit(selected);
      return;
    }
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const delta = moves[event.key];
    if (!delta) return;
    event.preventDefault();
    setPreview({
      x: Math.max(0, Math.min(14, selected.x + delta[0])),
      y: Math.max(0, Math.min(14, selected.y + delta[1])),
    });
  }
  return (
    <div className="gomoku-board-wrap">
      <svg
        viewBox={`0 0 ${BOARD_SIZE} ${BOARD_SIZE}`}
        className="gomoku-board"
        role={canAct ? 'button' : 'img'}
        tabIndex={canAct ? 0 : undefined}
        aria-label={`五子棋棋盘，${stones.length} 枚棋子${preview ? `，选中 ${coordinateLabel(preview)}` : ''}`}
        onKeyDown={keyboard}
        onFocus={() => {
          if (canAct) setPreview({ x: 7, y: 7 });
        }}
        onPointerMove={(event) => {
          if (canAct && event.pointerType === 'mouse') setPreview(pointFrom(event));
        }}
        onPointerLeave={() => {
          if (!touchPreview) setPreview(null);
        }}
        onPointerDown={(event) => {
          if (!canAct || event.button !== 0) return;
          const point = pointFrom(event);
          if (!point || !legal(point)) return;
          if (event.pointerType === 'mouse') submit(point);
          else {
            setPreview(point);
            setTouchPreview(true);
          }
        }}
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
          <radialGradient id={`${id}-black`} cx=".32" cy=".25" r=".7">
            <stop stopColor="#575553" />
            <stop offset=".5" stopColor="#28282b" />
            <stop offset="1" stopColor="#111218" />
          </radialGradient>
          <radialGradient id={`${id}-white`} cx=".32" cy=".25" r=".8">
            <stop stopColor="#fffef7" />
            <stop offset=".6" stopColor="#ede9de" />
            <stop offset="1" stopColor="#c4beb2" />
          </radialGradient>
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
        <rect x="3" y="3" width="594" height="594" rx="26" fill={`url(#${id}-edge)`} />
        <rect
          x="12"
          y="12"
          width="576"
          height="576"
          rx="19"
          fill={`url(#${id}-wood)`}
          stroke="var(--board-rim)"
        />
        <rect x="13" y="13" width="574" height="574" rx="18" fill={`url(#${id}-grain)`} />
        {Array.from({ length: 15 }, (_, i) => (
          <g key={i}>
            <path
              d={`M${GRID_ORIGIN} ${GRID_ORIGIN + i * GRID_STEP}H552 M${GRID_ORIGIN + i * GRID_STEP} ${GRID_ORIGIN}V552`}
              stroke="var(--board-line)"
              strokeWidth={i === 0 || i === 14 ? 1.5 : 0.9}
            />
            <text
              x={GRID_ORIGIN + i * GRID_STEP}
              y="31"
              textAnchor="middle"
              className="gomoku-coordinate"
            >
              {String.fromCharCode(65 + i)}
            </text>
            <text
              x="29"
              y={GRID_ORIGIN + i * GRID_STEP + 4}
              textAnchor="middle"
              className="gomoku-coordinate"
            >
              {i + 1}
            </text>
          </g>
        ))}
        {[
          [3, 3],
          [11, 3],
          [7, 7],
          [3, 11],
          [11, 11],
        ].map(([x, y]) => (
          <circle
            key={`${x}-${y}`}
            cx={GRID_ORIGIN + x! * GRID_STEP}
            cy={GRID_ORIGIN + y! * GRID_STEP}
            r="3"
            fill="var(--board-line)"
          />
        ))}
        {stones.map((stone) => (
          <g key={`${stone.x}-${stone.y}`}>
            <ellipse
              cx={GRID_ORIGIN + stone.x * GRID_STEP + 1}
              cy={GRID_ORIGIN + stone.y * GRID_STEP + 3}
              rx="16"
              ry="15"
              fill="var(--board-stone-shadow)"
            />
            <circle
              cx={GRID_ORIGIN + stone.x * GRID_STEP}
              cy={GRID_ORIGIN + stone.y * GRID_STEP}
              r="15.6"
              fill={`url(#${id}-${stone.seat_id})`}
              stroke={stone.seat_id === 'white' ? '#a29c91' : '#18191d'}
              strokeWidth=".6"
            />
          </g>
        ))}
        {last ? (
          <rect
            x={GRID_ORIGIN + last.x * GRID_STEP - 3}
            y={GRID_ORIGIN + last.y * GRID_STEP - 3}
            width="6"
            height="6"
            rx="1"
            fill={last.seat_id === 'black' ? '#ead4a6' : '#8e6941'}
          />
        ) : null}
        {canAct && preview ? (
          <circle
            cx={GRID_ORIGIN + preview.x * GRID_STEP}
            cy={GRID_ORIGIN + preview.y * GRID_STEP}
            r="15"
            fill={view?.viewer_seat_id === 'white' ? '#fffdf3' : '#25252a'}
            opacity={legal(preview) ? 0.55 : 0.15}
            stroke="var(--board-line)"
            strokeDasharray="3 3"
          />
        ) : null}
      </svg>
      {canAct && touchPreview && preview ? (
        <button
          type="button"
          className="game-button game-button-primary gomoku-confirm"
          onClick={() => submit(preview)}
        >
          确认落子 · {coordinateLabel(preview)}
        </button>
      ) : null}
    </div>
  );
}
