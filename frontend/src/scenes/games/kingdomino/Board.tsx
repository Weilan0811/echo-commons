import { useState } from 'react';
import type { GameAction, GameView } from '@/api/games';
import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';
import {
  displayBounds,
  castleIcon,
  coordKey,
  crownIcon,
  groupPlacements,
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

function LineTile({
  tile,
  clickable,
  active,
  label,
  onSelect,
}: {
  tile: Visible;
  clickable: boolean;
  active: boolean;
  label: string;
  onSelect?: (() => void) | undefined;
}) {
  const owner = tile.king_seat_id ? seatStyle('kingdomino', tile.king_seat_id) : null;
  const face = (
    <>
      <span className="kingdomino-tile-meta">
        <span>{tile.domino_id}</span>
        {owner ? (
          <span>
            <i className="game-stone-dot" style={{ background: owner.tone }} />
            {owner.label}
          </span>
        ) : (
          <span>可选</span>
        )}
      </span>
      <span className="kingdomino-domino">
        <TileHalf half={tile.a} />
        <TileHalf half={tile.b} />
      </span>
    </>
  );
  const className = `kingdomino-tile${clickable ? ' kingdomino-tile-selectable' : ''}${active ? ' kingdomino-tile-current' : ''}`;
  return clickable ? (
    <button type="button" className={className} aria-label={label} onClick={onSelect}>
      {face}
    </button>
  ) : (
    <div className={className} aria-label={label}>
      {face}
    </div>
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
    <div
      className={`kingdomino-kingdom${own ? ' kingdomino-kingdom-own' : ''}${active ? ' kingdomino-kingdom-active' : ''}`}
    >
      <header className="kingdomino-kingdom-head">
        <i className="game-stone-dot" style={{ background: mark.tone }} />
        <strong>{own ? '我的王国' : mark.label + '的王国'}</strong>
        <span>{own ? mark.label + ' · 你' : active ? '正在行动' : ''}</span>
        {score ? <b>{score.total} 分</b> : null}
      </header>
      <div
        className="kingdomino-grid"
        style={{
          gridTemplateColumns: `repeat(${bounds.columns}, minmax(0, 1fr))`,
        }}
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
  const [opponentSeat, setOpponentSeat] = useState<string | null>(null);
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
  const opponents = state.kingdoms.filter((kingdom) => kingdom.seat_id !== viewerSeat);
  const opponent = opponents.find((kingdom) => kingdom.seat_id === opponentSeat) ?? opponents[0];

  // 放置阶段的合法动作：可能给出多个落点与朝向，也可能只有弃置。
  const placeActions = legal.filter(
    (action): action is PlaceAction => action.type === 'place_domino',
  );
  const canDiscard = legal.some((action) => action.type === 'discard_domino');
  const groups = placeActions.length ? groupPlacements(placeActions) : [];
  const activeTile =
    phase === 'placing' && state.active_domino_id !== null
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
      ? {
          a: anchorGroup.cell,
          b: nextCoord(anchorGroup.cell, selectedDirection),
          tile: activeTile!,
        }
      : null;

  const candidates = new Set(groups.map((group) => coordKey(group.cell)));
  const viewerKingdom = state.kingdoms.find((kingdom) => kingdom.seat_id === viewerSeat) ?? null;

  // 放置阶段的画布范围要把所有候选落点与它们的 B 格一起算进来，避免预览落在网格之外。
  const points: Coord[] = (viewerKingdom?.cells ?? []).map((cell) => ({
    x: cell.x,
    y: cell.y,
  }));
  for (const group of groups) {
    points.push(group.cell);
    for (const direction of group.directions) points.push(nextCoord(group.cell, direction));
  }
  const bounds = displayBounds(points);

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
  else if (phase === 'seeding') hint = '在本轮地块中选择一张，放置你的国王';
  else if (phase === 'placing') {
    hint = canDiscard
      ? '这张地块在你的王国里没有合法落点，只能弃置'
      : anchorGroup
        ? '确认朝向，把地块放到所选落点'
        : '在你的王国里选择一个落点';
  } else hint = '在下轮地块中选择一张，放置你的国王';

  const renderKingdom = (kingdom: KingdomData) => {
    const own = kingdom.seat_id === viewerSeat;
    const interactive = own && canAct && phase === 'placing' && groups.length > 0;
    return (
      <KingdomCard
        key={kingdom.seat_id}
        kingdom={kingdom}
        active={currentSeat === kingdom.seat_id}
        own={own}
        bounds={own ? bounds : displayBounds(kingdom.cells)}
        cellMap={new Map(kingdom.cells.map((cell) => [coordKey(cell), cell]))}
        candidates={interactive ? candidates : new Set<string>()}
        anchorKey={interactive ? anchorKey : null}
        ghost={interactive ? ghost : null}
        score={scoreOf(kingdom.seat_id)}
        onPick={interactive ? pick : undefined}
      />
    );
  };
  const previewDirection = selectedDirection ?? 'right';
  return (
    <div className="kingdomino-board-wrap">
      <div className="kingdomino-workspace">
        <section className="kingdomino-main" aria-label="我的王国">
          {viewerKingdom ? renderKingdom(viewerKingdom) : null}
        </section>
        <aside className="kingdomino-sidebar" aria-label="地块与对手王国">
          <section className="kingdomino-line-panel" aria-label="本轮地块">
            <header>
              <h2>本轮地块</h2>
              <span>
                {phase === 'finished'
                  ? '本局最后一轮'
                  : phase === 'seeding'
                    ? '选择地块放置国王'
                    : '按编号依次行动'}
              </span>
            </header>
            <div className="kingdomino-line-tiles">
              {state.line.map((slot) => (
                <LineTile
                  key={slot.domino_id}
                  tile={slot}
                  active={slot.domino_id === state.active_domino_id}
                  label={`选择本轮地块 ${slot.domino_id}`}
                  clickable={canAct && phase === 'seeding' && !slot.king_seat_id}
                  onSelect={() =>
                    act({
                      type: 'place_initial_king',
                      domino_id: slot.domino_id,
                    })
                  }
                />
              ))}
            </div>
          </section>
          <section className="kingdomino-line-panel" aria-label="下轮地块">
            <header>
              <h2>下轮地块</h2>
              <span>
                {phase === 'finished'
                  ? '已结算'
                  : phase === 'choosing'
                    ? '选择下一轮的地块'
                    : '放置后选择'}
              </span>
            </header>
            <div className="kingdomino-line-tiles">
              {state.next_line.length ? (
                state.next_line.map((slot) => (
                  <LineTile
                    key={slot.domino_id}
                    tile={slot}
                    active={false}
                    label={`选择下轮地块 ${slot.domino_id}`}
                    clickable={canAct && phase === 'choosing' && !slot.king_seat_id}
                    onSelect={() => act({ type: 'choose_domino', domino_id: slot.domino_id })}
                  />
                ))
              ) : (
                <span className="kingdomino-line-empty">没有下轮地块</span>
              )}
            </div>
          </section>
          <section className="kingdomino-opponents" aria-label="对手的王国">
            {opponents.length > 1 ? (
              <div className="kingdomino-opponent-tabs" role="group" aria-label="选择对手王国">
                {opponents.map((kingdom) => {
                  const mark = seatStyle('kingdomino', kingdom.seat_id);
                  return (
                    <button
                      key={kingdom.seat_id}
                      type="button"
                      aria-label={`查看${mark.label}的王国`}
                      aria-pressed={opponent?.seat_id === kingdom.seat_id}
                      onClick={() => setOpponentSeat(kingdom.seat_id)}
                    >
                      <i className="game-stone-dot" style={{ background: mark.tone }} />
                      {mark.label}
                      {currentSeat === kingdom.seat_id ? <small>行动中</small> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}
            {opponent ? renderKingdom(opponent) : null}
          </section>
        </aside>
      </div>
      <div className="kingdomino-hud">
        {activeTile ? (
          <div className="kingdomino-preview" aria-label={`待放置地块 ${activeTile.domino_id}`}>
            <span>待放置地块</span>
            <div className="kingdomino-preview-space">
              <div
                className={`kingdomino-domino kingdomino-preview-domino kingdomino-direction-${previewDirection}`}
              >
                <TileHalf half={activeTile.a} />
                <TileHalf half={activeTile.b} />
              </div>
            </div>
          </div>
        ) : null}
        <div className="kingdomino-hud-copy" role="status">
          <p className="kingdomino-hud-turn">
            {gamePhaseLabel('kingdomino', phase)}
            {selectedDirection ? <span>朝向：{DIRECTION_LABEL[selectedDirection]}</span> : null}
          </p>
          <p className="kingdomino-hud-hint">{hint}</p>
          {phase === 'seeding' && state.seeding_remaining > 0 ? (
            <small>待放国王 {state.seeding_remaining} 枚</small>
          ) : null}
        </div>
        {canAct && phase === 'placing' && !canDiscard ? (
          <div className="kingdomino-hud-actions">
            <button
              type="button"
              className="game-button game-button-quiet"
              disabled={!anchorGroup}
              onClick={clearAnchor}
            >
              重选落点
            </button>
            <button
              type="button"
              className="game-button game-button-quiet"
              disabled={anchorDirections.length < 2}
              onClick={() => setDirectionIndex((index) => index + 1)}
            >
              旋转地块
            </button>
            <button
              type="button"
              className="game-button game-button-primary"
              disabled={!anchorGroup}
              onClick={confirmPlace}
            >
              确认放置
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
          <span>牌堆剩余 {state.deck_remaining} 张</span>
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
                    <b>{score.total} 分</b>
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
