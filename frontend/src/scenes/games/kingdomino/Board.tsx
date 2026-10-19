import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';

// M1 只接通视图与动作契约，这里先给出可核对的局势读数，王国与国王线在下一阶段接入。
export function Board(props: BoardProps) {
  const view = props.view;
  if (view && view.game_type !== 'kingdomino') return null;
  const state = view?.state ?? null;
  return (
    <section className="game-empty flex w-full max-w-xl flex-col gap-4" aria-label="Kingdomino 棋盘">
      <span>Kingdomino 王国与国王线将在下一阶段接入，下面是本局的实时局势。</span>
      {state ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-left text-xs text-content-faint">
          <dt>阶段</dt>
          <dd>{gamePhaseLabel('kingdomino', state.phase)}</dd>
          <dt>当前席位</dt>
          <dd>{seatStyle('kingdomino', state.current_seat_id ?? '').label}</dd>
          <dt>牌堆剩余</dt>
          <dd>{state.deck_remaining} 张</dd>
          <dt>国王线</dt>
          <dd>
            {state.line.filter((slot) => slot.king_seat_id).length}／{state.line.length} 已放王
          </dd>
          <dt>已弃置</dt>
          <dd>{state.discarded.length} 张</dd>
          <dt>王国</dt>
          <dd className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {state.kingdoms.map((kingdom) => {
              const mark = seatStyle('kingdomino', kingdom.seat_id);
              return (
                <span key={kingdom.seat_id} className="inline-flex items-center gap-1">
                  <i className="game-stone-dot" style={{ background: mark.tone }} />
                  {mark.label}
                  {kingdom.cells.length} 格
                </span>
              );
            })}
          </dd>
        </dl>
      ) : (
        <span>等待对局开始</span>
      )}
    </section>
  );
}
