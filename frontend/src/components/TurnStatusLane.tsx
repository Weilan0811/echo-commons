import type { TurnDisplay, ParticipantDisplay } from '@/lib/deriveTurnStates';
import { accentColor } from '@/lib/characterColor';

interface TurnStatusLaneProps {
  readonly displays: readonly TurnDisplay[];
  /** 角色标识到显示名的解析。 */
  readonly resolveName: (characterId: string) => string;
}

/**
 * 轮次状态栏。位于输入器上方。
 *
 * 契约说明轮次完成且没有角色消息属于正常状态，因此此处不把「没有消息」
 * 呈现为故障；沉默与失败必须区分，前者是角色选择不发言，后者是执行出错。
 */
export function TurnStatusLane({ displays, resolveName }: TurnStatusLaneProps) {
  const recent = displays.slice(-3);
  if (recent.length === 0) return null;

  const hasVisible = recent.some((display) =>
    display.participants.some((participant) => participant.state !== 'completed'),
  );
  const hasResponding = recent.some((display) =>
    display.participants.some((participant) => participant.state === 'responding'),
  );
  const chainActive = displays.some((display) => display.chainActive);

  if (!hasVisible && !hasResponding && !chainActive) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1 text-xs">
      {chainActive ? <span className="animate-breathe text-content-muted">对话正在继续…</span> : null}
      {recent.map((display) =>
        display.participants.map((participant) => (
          <ParticipantState
            key={`${display.turnId}-${participant.characterId}`}
            characterId={participant.characterId}
            name={resolveName(participant.characterId)}
            state={participant.state}
          />
        )),
      )}
    </div>
  );
}

const STATE_LABEL: Record<ParticipantDisplay, string> = {
  waiting: '等待发言',
  responding: '正在回应',
  silent: '选择沉默',
  failed: '回应失败',
  cancelled: '已取消',
  completed: '',
};

function ParticipantState({
  characterId,
  name,
  state,
}: {
  readonly characterId: string;
  readonly name: string;
  readonly state: ParticipantDisplay;
}) {
  const label = STATE_LABEL[state];
  // 已完成且非失败的状态不显示文字，避免状态栏堆满历史信息。
  if (label === '') return null;

  const tone =
    state === 'failed'
      ? 'text-danger'
      : state === 'responding'
        ? 'text-content-muted'
        : 'text-content-faint';

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`size-1.5 rounded-full ${state === 'responding' ? 'animate-breathe' : ''}`}
        style={{
          backgroundColor:
            state === 'failed'
              ? 'var(--color-danger)'
              : state === 'responding'
                ? accentColor(characterId)
                : 'var(--color-border-strong)',
        }}
        aria-hidden="true"
      />
      <span className={tone}>
        {name}
        {state === 'responding' ? '正在回应' : label}
      </span>
    </span>
  );
}
