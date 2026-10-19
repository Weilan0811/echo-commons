import { gamePhaseLabel, seatStyle, type BoardProps } from '@/features/games/presentation';

// M1 只接通视图与动作契约，这里先给出可核对的局势读数，棋盘绘制在下一阶段接入。
export function Board(props: BoardProps) {
  const view = props.view;
  if (view && view.game_type !== 'aeroplane') return null;
  const state = view?.state ?? null;
  return (
    <section className="game-empty flex w-full max-w-xl flex-col gap-4" aria-label="飞行棋棋盘">
      <span>飞行棋棋盘将在下一阶段接入，下面是本局的实时局势。</span>
      {state ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-left text-xs text-content-faint">
          <dt>阶段</dt>
          <dd>{gamePhaseLabel('aeroplane', state.phase)}</dd>
          <dt>当前席位</dt>
          <dd>{seatStyle('aeroplane', state.current_seat_id ?? '').label}</dd>
          <dt>骰子</dt>
          <dd>{state.dice ?? '未掷'}</dd>
          <dt>连续六</dt>
          <dd>{state.consecutive_sixes}</dd>
          <dt>机场棋子</dt>
          <dd className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {state.seat_order.map((seatId) => {
              const atBase = state.planes.filter(
                (plane) => plane.seat_id === seatId && plane.step === null,
              ).length;
              const mark = seatStyle('aeroplane', seatId);
              return (
                <span key={seatId} className="inline-flex items-center gap-1">
                  <i className="game-stone-dot" style={{ background: mark.tone }} />
                  {mark.label}
                  {atBase}／4
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
