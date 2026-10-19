import { useState } from 'react';
import type { GameAction, GameView } from '@/api/games';
import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';
import {
  boundsOf,
  castleIcon,
  coordKey,
  crownIcon,
  groupPlacements,
  gridPosition,
  nextCoord,
  terrainTexture,
  type Bounds,
  type Coord,
  type Direction,
  type PlaceAction,
} from './layout';

type KingdominoState = Extract<GameView, { game_type: 'kingdomino' }>['state'];
type Visible = KingdominoState['line'][number];
type VisibleHalf = Visible['a'];
type KingdomData = KingdominoState['kingdoms'][number];
type KingdomCell = KingdomData['cells'][number];

// 朝向在托盘与按钮上显示的说明文字，与规则文档第 6 节的四向一致。
const DIRECTION_LABEL: Record<Direction, string> = {
  right: '向右',
  down: '向下',
  left: '向左',
  up: '向上',
};

// 3×3 托盘里 B 格相对 A 格（正中格）的索引偏移。
const TRAY_DELTA: Record<Direction, number> = { right: 1, down: 3, left: -1, up: -3 };
const TRAY_SIZE = 3;

function TileHalf({ half, className }: { half: VisibleHalf; className?: string }) {
  return (
    <span
      className={`kingdomino-half${className ? ` ${className}` : ''}`}
      style={{ backgroundImage: `url(${terrainTexture(half.terrain)})` }}
    >
      {half.crowns > 0 ? (
        <span className="kingdomino-crowns">
          {Array.from({ length: half.crowns }, (_, index) => (
            <img key={index} src={crownIcon()} alt="" />
          ))}
        </span>
      ) : null}
    </span>
  );
}

function KingMark({ seatId }: { seatId: string }) {
  return (
    <img
      className="kingdomino-king"
      src={castleIcon(seatId)}
      alt={`${seatStyle('kingdomino', seatId).label}国王`}
    />
  );
}

// 国王线与新线里的一张地块：两格地形 + 可选国王 + 编号。
function LineTile({
  tile,
  clickable,
  label,
  onSelect,
}: {
  tile: Visible;
  clickable: boolean;
  label: string;
  onSelect?: (() => void) | undefined;
}) {
  const face = (
    <>
      <TileHalf half={tile.a} />
      <TileHalf half={tile.b} />
      {tile.king_seat_id ? <KingMark seatId={tile.king_seat_id} /> : null}
      <span className="kingdomino-tile-id">{tile.domino_id}</span>
    </>
  );
  if (!clickable) {
    return (
      <span className="kingdomino-tile" aria-label={label}>
        {face}
      </span>
    );
  }
  return (
    <button type="button" className="kingdomino-tile kingdomino-tile-active" onClick={onSelect}>
      {face}
    </button>
  );
}

function KingdomCard({
  kingdom,
  active,
  own,
  bounds,
  cellMap,
  candidates,
  anchorKey,
  ghost,
  score,
  onPick,
}: {
  kingdom: KingdomData;
  active: boolean;
  own: boolean;
  bounds: Bounds;
  cellMap: Map<string, KingdomCell>;
  candidates: Set<string>;
  anchorKey: string | null;
  ghost: { a: Coord; b: Coord; tile: Visible } | null;
  score: { total: number; largest_domain: number; crowns: number } | undefined;
  onPick?: ((cell: Coord) => void) | undefined;
}) {
  const mark = seatStyle('kingdomino', kingdom.seat_id);
  return (
    <div className={`kingdomino-kingdom${active ? ' kingdomino-kingdom-active' : ''}`}>
      <header className="kingdomino-kingdom-head">
        <i className="game-stone-dot" style={{ background: mark.tone }} />
        <span>{mark.label}</span>
        {own ? <em>你</em> : null}
        {score ? <strong>{score.total} 分</strong> : null}
      </header>
      <div
        className="kingdomino-grid"
        style={{ gridTemplateColumns: `repeat(${bounds.columns}, var(--k-cell))` }}
      >
        {Array.from({ length: bounds.columns * bounds.rows }, (_, index) => {
          const column = index % bounds.columns;
          const row = Math.floor(index / bounds.columns);
          const cell: Coord = { x: bounds.minX + column, y: bounds.maxY - row };
          const key = coordKey(cell);
          const placed = cellMap.get(key);
          const ghostHalf =
            ghost && coordKey(ghost.a) === key
              ? ghost.tile.a
              : ghost && coordKey(ghost.b) === key
                ? ghost.tile.b
                : null;
          const isCandidate = candidates.has(key);
          if (ghostHalf) {
            return (
              <span key={key} className="kingdomino-cell kingdomino-cell-ghost">
                <TileHalf half={ghostHalf} />
              </span>
            );
          }
          if (placed) {
            return (
              <span key={key} className="kingdomino-cell">
                <TileHalf half={placed} />
                {placed.start ? (
                  <img
                    className="kingdomino-castle"
                    src={castleIcon(kingdom.seat_id)}
                    alt="起始城堡"
                  />
                ) : null}
              </span>
            );
          }
          if (isCandidate && onPick) {
            return (
              <button
                key={key}
                type="button"
                className={`kingdomino-cell kingdomino-cell-target${
                  anchorKey === key ? ' kingdomino-cell-anchor' : ''
                }`}
                aria-label={`放置到第 ${cell.x} 列第 ${cell.y} 行`}
                onClick={() => onPick(cell)}
              />
            );
          }
          return <span key={key} className="kingdomino-cell kingdomino-cell-empty" />;
        })}
      </div>
    </div>
  );
}

export function Board(props: BoardProps) {
  const view = props.view;
  const { onAction, pending = false } = props;
  const [anchorKey, setAnchorKey] = useState<string | null>(null);
  const [directionIndex, setDirectionIndex] = useState(0);
  // 视图联合按 game_type 收窄后，本组件只处理 Kingdomino 视图。
  if (view && view.game_type !== 'kingdomino') return null;
  const state = view?.state ?? null;
  const opportunity = view?.opportunities[0];
  const legal: readonly GameAction[] = opportunity?.legal_actions ?? [];
  const canAct = !!onAction && !!opportunity && !pending;
  if (!state) return <span className="game-empty">等待对局开始</span>;

  const phase = state.phase;
  const viewerSeat = view?.viewer_seat_id ?? '';
  const currentSeat = state.current_seat_id;
  const seatMark = currentSeat ? seatStyle('kingdomino', currentSeat) : null;
  const result = state.result;

  // 放置阶段的合法动作：可能给出多个落点与朝向，也可能只有弃置。
  const placeActions = legal.filter((action): action is PlaceAction => action.type === 'place_domino');
  const canDiscard = legal.some((action) => action.type === 'discard_domino');
  const groups = placeActions.length ? groupPlacements(placeActions) : [];
  const activeTile =
    state.active_domino_id !== null
      ? (state.line.find((slot) => slot.domino_id === state.active_domino_id) ?? null)
      : null;

  const anchorGroup = groups.find((group) => coordKey(group.cell) === anchorKey) ?? null;
  const anchorDirections = anchorGroup?.directions ?? [];
  const selectedDirection =
    anchorDirections.length > 0
      ? anchorDirections[directionIndex % anchorDirections.length]!
      : null;
  const ghost =
    anchorGroup && selectedDirection
      ? { a: anchorGroup.cell, b: nextCoord(anchorGroup.cell, selectedDirection), tile: activeTile! }
      : null;

  const candidates = new Set(groups.map((group) => coordKey(group.cell)));
  const viewerKingdom = state.kingdoms.find((kingdom) => kingdom.seat_id === viewerSeat) ?? null;

  // 放置阶段的画布范围要把所有候选落点与它们的 B 格一起算进来，避免预览落在网格之外。
  const points: Coord[] = (viewerKingdom?.cells ?? []).map((cell) => ({ x: cell.x, y: cell.y }));
  for (const group of groups) {
    points.push(group.cell);
    for (const direction of group.directions) points.push(nextCoord(group.cell, direction));
  }
  const bounds = boundsOf(points.length ? points : [{ x: 0, y: 0 }]);

  const scoreOf = (seatId: string) =>
    result?.scores.find((score) => score.seat_id === seatId) ?? undefined;

  const act = (action: GameAction) => {
    if (canAct) onAction?.(action);
  };
  const pick = (cell: Coord) => {
    setAnchorKey(coordKey(cell));
    setDirectionIndex(0);
  };
  const clearAnchor = () => {
    setAnchorKey(null);
    setDirectionIndex(0);
  };
  const confirmPlace = () => {
    if (!anchorGroup || !selectedDirection) return;
    act({
      type: 'place_domino',
      cell_x: anchorGroup.cell.x,
      cell_y: anchorGroup.cell.y,
      direction: selectedDirection,
    });
  };

  let hint: string;
  if (phase === 'finished') hint = '本局已结算';
  else if (!canAct) hint = `等${seatMark?.label ?? '对手'}行动`;
  else if (phase === 'seeding') hint = '在国王线选择一张没有国王的地块，放下你的国王';
  else if (phase === 'placing') {
    hint = canDiscard
      ? '这张地块在你的王国里没有合法落点，只能弃置'
      : anchorGroup
        ? '确认朝向，把地块放到所选落点'
        : '在你的王国里选择一个落点';
  } else hint = '在新线选择一张没有国王的地块，放上你的国王';

  return (
    <div className="kingdomino-board-wrap">
      <div className="kingdomino-lines">
        <div className="kingdomino-line-row">
          <span className="kingdomino-line-label">国王线</span>
          <div className="kingdomino-line-tiles">
            {state.line.map((slot) => (
              <LineTile
                key={slot.domino_id}
                tile={slot}
                label={`地块 ${slot.domino_id}`}
                clickable={canAct && phase === 'seeding' && !slot.king_seat_id}
                onSelect={() => act({ type: 'place_initial_king', domino_id: slot.domino_id })}
              />
            ))}
          </div>
        </div>
        <div className="kingdomino-line-row">
          <span className="kingdomino-line-label">新线</span>
          <div className="kingdomino-line-tiles">
            {state.next_line.length ? (
              state.next_line.map((slot) => (
                <LineTile
                  key={slot.domino_id}
                  tile={slot}
                  label={`地块 ${slot.domino_id}`}
                  clickable={canAct && phase === 'choosing' && !slot.king_seat_id}
                  onSelect={() => act({ type: 'choose_domino', domino_id: slot.domino_id })}
                />
              ))
            ) : (
              <span className="kingdomino-line-empty">牌堆已空</span>
            )}
          </div>
        </div>
      </div>

      <section className="kingdomino-kingdoms" aria-label="各家王国">
        {state.kingdoms.map((kingdom) => {
          const own = kingdom.seat_id === viewerSeat;
          const cellMap = new Map(kingdom.cells.map((cell) => [coordKey(cell), cell]));
          const interactive = own && canAct && phase === 'placing' && groups.length > 0;
          // 只有观看者自己的王国需要把候选落点算进画布，其他王国按各自已占格取范围。
          const kingdomBounds = own
            ? bounds
            : boundsOf(kingdom.cells.map((cell) => ({ x: cell.x, y: cell.y })));
          return (
            <KingdomCard
              key={kingdom.seat_id}
              kingdom={kingdom}
              active={currentSeat === kingdom.seat_id}
              own={own}
              bounds={kingdomBounds}
              cellMap={cellMap}
              candidates={interactive ? candidates : new Set<string>()}
              anchorKey={interactive ? anchorKey : null}
              ghost={interactive ? ghost : null}
              score={scoreOf(kingdom.seat_id)}
              onPick={interactive ? pick : undefined}
            />
          );
        })}
      </section>

      <div className="kingdomino-hud">
        <div className="kingdomino-hud-status">
          {activeTile ? (
            <div
              className="kingdomino-tray"
              style={{
                gridTemplateColumns: `repeat(${TRAY_SIZE}, 1fr)`,
                gridTemplateRows: `repeat(${TRAY_SIZE}, 1fr)`,
              }}
              aria-label={`待放置地块 ${activeTile.domino_id}`}
            >
              {Array.from({ length: TRAY_SIZE * TRAY_SIZE }, (_, index) => {
                const center = 4;
                const delta = selectedDirection ? TRAY_DELTA[selectedDirection] : 0;
                if (index === center) return <TileHalf key={index} half={activeTile.a} />;
                if (selectedDirection && index === center + delta)
                  return <TileHalf key={index} half={activeTile.b} />;
                return <span key={index} className="kingdomino-tray-slot" />;
              })}
            </div>
          ) : null}
          <div className="kingdomino-hud-copy">
            <p className="kingdomino-hud-turn">
              {seatMark ? (
                <>
                  <i className="game-stone-dot" style={{ background: seatMark.tone }} />
                  {seatMark.label}
                </>
              ) : null}
              <span>{gamePhaseLabel('kingdomino', phase)}</span>
            </p>
            <p className="kingdomino-hud-hint">
              {hint}
              {phase === 'seeding' && state.seeding_remaining > 0 ? (
                <span className="kingdomino-hud-meta">待放国王 {state.seeding_remaining} 枚</span>
              ) : null}
            </p>
          </div>
        </div>
        {canAct && phase === 'placing' && anchorGroup ? (
          <div className="kingdomino-hud-actions">
            <button type="button" className="game-button game-button-quiet" onClick={clearAnchor}>
              重选落点
            </button>
            {anchorDirections.length > 1 ? (
              <button
                type="button"
                className="game-button game-button-quiet"
                onClick={() => setDirectionIndex((index) => index + 1)}
              >
                旋转地块
              </button>
            ) : null}
            <button type="button" className="game-button game-button-primary" onClick={confirmPlace}>
              放到这里{selectedDirection ? `（${DIRECTION_LABEL[selectedDirection]}）` : ''}
            </button>
          </div>
        ) : null}
        {canAct && phase === 'placing' && canDiscard ? (
          <div className="kingdomino-hud-actions">
            <button
              type="button"
              className="game-button game-button-primary"
              onClick={() => act({ type: 'discard_domino' })}
            >
              弃置这张地块
            </button>
          </div>
        ) : null}
        <div className="kingdomino-hud-meta-row">
          <span>牌堆余 {state.deck_remaining} 张</span>
          <span>已弃置 {state.discarded.length} 张</span>
        </div>
      </div>

      {result ? (
        <div className="kingdomino-result">
          <p className="kingdomino-result-title">
            {result.winner_seat_ids
              .map((seatId) => seatStyle('kingdomino', seatId).label)
              .join('、')}
            获胜
          </p>
          <ul>
            {[...result.scores]
              .sort(
                (left, right) =>
                  right.total - left.total ||
                  right.largest_domain - left.largest_domain ||
                  right.crowns - left.crowns,
              )
              .map((score) => {
                const mark = seatStyle('kingdomino', score.seat_id);
                const winner = result.winner_seat_ids.includes(score.seat_id);
                return (
                  <li key={score.seat_id} className={winner ? 'kingdomino-result-win' : undefined}>
                    <i className="game-stone-dot" style={{ background: mark.tone }} />
                    <span>{mark.label}</span>
                    <strong>{score.total} 分</strong>
                    <small>
                      最大领域 {score.largest_domain} 格 · 皇冠 {score.crowns}
                    </small>
                  </li>
                );
              })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
