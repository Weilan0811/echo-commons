import {
  BOARD_VIEW,
  HOMESTRETCH,
  SEAT_FILL,
  SEAT_ORDER,
  TAKEOFF_CELL,
  TILE,
  baseBounds,
  baseSlot,
  cellCenter,
  homeEntry,
  ringCellCenter,
  RING_CELLS,
  seatOfCell,
  shortcutLink,
  waitingSpot,
  rotateCell,
  type SeatId,
} from './coordinates';

const seatNames: Record<SeatId, string> = {
  red: '红方',
  yellow: '黄方',
  blue: '蓝方',
  green: '绿方',
};

export function BoardArtwork({
  activeShortcut,
}: {
  activeShortcut: SeatId | null;
}) {
  const ring = RING_CELLS;
  return (
    <g aria-hidden="true" pointerEvents="none">
      <rect x="5" y="5" width={BOARD_VIEW - 10} height={BOARD_VIEW - 10} rx="26" fill="#bba377" />
      <rect
        x="15"
        y="15"
        width="970"
        height="970"
        rx="20"
        fill="#faf7ed"
        stroke="#705d44"
        strokeWidth="2"
      />
      <rect x="29" y="29" width="942" height="942" rx="12" fill="none" stroke="#d9d0be" />

      {ring.map((cell, index) => {
        const center = cellCenter(cell);
        const next = cellCenter(ring[(index + 1) % ring.length]!);
        return (
          <path
            key={`link-${index}`}
            d={`M${center.x} ${center.y}L${next.x} ${next.y}`}
            stroke={SEAT_FILL[seatOfCell(index)].cell}
            strokeWidth={TILE}
          />
        );
      })}
      {ring.map((cell, index) => {
        const center = cellCenter(cell);
        return (
          <rect
            key={`tile-${index}`}
            x={center.x - TILE / 2}
            y={center.y - TILE / 2}
            width={TILE}
            height={TILE}
            fill={SEAT_FILL[seatOfCell(index)].cell}
            stroke="#faf7ed"
            strokeWidth="1.5"
          />
        );
      })}

      {SEAT_ORDER.map((seat, turn) => {
        const entry = homeEntry(seat);
        const last = cellCenter(HOMESTRETCH[seat][5]!);
        const arrow = [
          [6.52, 5.75],
          [7.48, 5.75],
          [7.48, 6.2],
          [7.85, 6.2],
          [7, 7],
          [6.15, 6.2],
          [6.52, 6.2],
        ].map(([x, y]) => cellCenter(rotateCell([x!, y!], turn)));
        return (
          <g key={`lane-${seat}`} data-home-lane={seat}>
            <path
              d={`M${entry.x} ${entry.y}L${last.x} ${last.y}`}
              stroke={SEAT_FILL[seat].cell}
              strokeWidth={TILE - 2}
            />
            <polygon
              points={arrow.map(({ x, y }) => `${x},${y}`).join(' ')}
              fill={SEAT_FILL[seat].cell}
              stroke="#faf7ed"
              strokeWidth="2"
            />
          </g>
        );
      })}

      {SEAT_ORDER.map((seat) => {
        const { from, to } = shortcutLink(seat);
        const active = activeShortcut === seat;
        const angle = (Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI;
        return (
          <g key={`shortcut-${seat}`} data-shortcut={seat} data-active={active}>
            <path
              d={`M${from.x} ${from.y}L${to.x} ${to.y}`}
              fill="none"
              stroke={SEAT_FILL[seat].deep}
              strokeWidth={active ? 4.5 : 2.5}
              strokeDasharray="7 8"
              opacity={active ? 1 : 0.4}
            />
            <path
              d="M-9 -6L0 0L-9 6"
              fill="none"
              stroke={SEAT_FILL[seat].deep}
              strokeWidth={active ? 4 : 2.5}
              opacity={active ? 1 : 0.6}
              transform={`translate(${from.x + (to.x - from.x) * 0.3} ${from.y + (to.y - from.y) * 0.3}) rotate(${angle})`}
            />
          </g>
        );
      })}

      {ring.map((cell, index) => {
        const { x, y } = cellCenter(cell);
        return (
          <circle
            key={`ring-${index}`}
            cx={x}
            cy={y}
            r="19"
            fill="#fffdf3"
            stroke={SEAT_FILL[seatOfCell(index)].deep}
            strokeWidth="1.4"
          />
        );
      })}
      {SEAT_ORDER.map((seat) => {
        const entry = homeEntry(seat);
        return (
          <g key={`home-${seat}`}>
            <circle
              data-entry={seat}
              cx={entry.x}
              cy={entry.y}
              r="19"
              fill="#fffdf3"
              stroke={SEAT_FILL[seat].deep}
              strokeWidth="1.4"
            />
            {HOMESTRETCH[seat].map((cell, index) => {
              const { x, y } = cellCenter(cell);
              return (
                <circle
                  key={index}
                  cx={x}
                  cy={y}
                  r="17"
                  fill="#fffdf3"
                  stroke={SEAT_FILL[seat].deep}
                  strokeWidth="1.3"
                />
              );
            })}
          </g>
        );
      })}

      {SEAT_ORDER.map((seat) => {
        const { x, y, size } = baseBounds(seat);
        const gate = waitingSpot(seat);
        const target = ringCellCenter(TAKEOFF_CELL[seat]);
        const dx = target.x - gate.x,
          dy = target.y - gate.y;
        const distance = Math.hypot(dx, dy);
        const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
        return (
          <g key={`base-${seat}`}>
            <rect
              x={x}
              y={y}
              width={size}
              height={size}
              rx="8"
              fill="#fffdf5"
              stroke={SEAT_FILL[seat].cell}
              strokeWidth="5"
            />
            <text
              x={x + size / 2}
              y={y + 16}
              textAnchor="middle"
              fontSize="12"
              fontWeight="700"
              fill={SEAT_FILL[seat].deep}
            >
              {seatNames[seat]}机场
            </text>
            {[1, 2, 3, 4].map((plane) => {
              const point = baseSlot(seat, plane);
              return (
                <circle key={plane} cx={point.x} cy={point.y} r="29" fill={SEAT_FILL[seat].cell} />
              );
            })}
            <path
              d={`M${gate.x + (dx / distance) * 23} ${gate.y + (dy / distance) * 23}L${target.x - (dx / distance) * 25} ${target.y - (dy / distance) * 25}`}
              stroke={SEAT_FILL[seat].deep}
              strokeWidth="3"
            />
            <circle
              cx={gate.x}
              cy={gate.y}
              r="22"
              fill={SEAT_FILL[seat].cell}
              stroke="#fffdf3"
              strokeWidth="2"
            />
            <path
              d="M-7 -7L3 0L-7 7"
              fill="none"
              stroke="#fffdf3"
              strokeWidth="3"
              transform={`translate(${gate.x} ${gate.y}) rotate(${angle})`}
            />
          </g>
        );
      })}
      <title>四色归航箭头汇入中央终点</title>
    </g>
  );
}
