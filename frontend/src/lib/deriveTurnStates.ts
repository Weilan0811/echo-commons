import type { SchemaOf } from '@/api/http';

type TurnView = SchemaOf<'TurnView'>;
type ParticipationView = SchemaOf<'ParticipationView'>;
type ParticipationStatus = ParticipationView['status'];

/**
 * 单个角色在状态栏中的显示状态。
 *
 * 契约中轮次完成且没有角色消息属于正常状态，因此 completed 不作为异常展示；
 * silent 与 failed 必须区分：前者是角色选择不发言，后者是执行出错。
 */
export type ParticipantDisplay =
  | 'responding'
  | 'silent'
  | 'failed'
  | 'cancelled'
  | 'completed';

export interface TurnDisplay {
  readonly turnId: string;
  readonly chainActive?: boolean;
  readonly participants: readonly ParticipantDisplayEntry[];
}

export interface ParticipantDisplayEntry {
  readonly characterId: string;
  readonly state: ParticipantDisplay;
  /** 规划选择次序。契约说明它不保证发言完成顺序，界面不据此排序。 */
  readonly selectionOrder: number | null;
}

/**
 * 把参与状态映射为显示状态。
 *
 * `selected` 表示已被安排回应。轮次仍在进行时显示为正在回应；
 * 轮次结束后同一状态表示已完成。
 */
function toDisplayState(
  status: ParticipationStatus,
  turnStatus: TurnView['status'],
  outcome: string | null,
): ParticipantDisplay {
  if (status === 'failed') return 'failed';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'silent') return 'silent';
  // 契约说明被选择角色主动沉默也记为 completed，outcome 为 silent。
  if (outcome === 'silent') return 'silent';
  if (status === 'completed') return 'completed';
  if (status === 'selected') {
    return turnStatus === 'running' ? 'responding' : 'completed';
  }
  return 'completed';
}

/**
 * 推导轮次中每个角色的显示状态，供状态栏呈现。
 *
 * 输入需按创建时间升序；界面据此由旧到新展示状态变化过程。
 */
export function deriveTurnStates(turns: readonly TurnView[]): TurnDisplay[] {
  return turns.map((turn) => ({
    turnId: turn.social_turn_id,
    chainActive: turn.chain_status === 'active',
    participants: turn.participation.map((participation) => ({
      characterId: participation.character_id,
      state: toDisplayState(participation.status, turn.status, participation.outcome),
      selectionOrder: participation.selection_order,
    })),
  }));
}

/** 处于进行中的轮次数量，用于决定状态栏是否显示活动指示。 */
export function countActiveTurns(turns: readonly TurnView[]): number {
  return new Set(turns.filter((turn) => turn.chain_status === 'active' || (!turn.chain_id && turn.status === 'running')).map((turn) => turn.chain_id ?? turn.social_turn_id)).size;
}

/** 收集当前正在回应的角色身份。 */
export function collectResponding(
  displays: readonly TurnDisplay[],
): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const display of displays) {
    for (const participant of display.participants) {
      if (participant.state === 'responding') ids.add(participant.characterId);
    }
  }
  return ids;
}

/** 收集执行失败的轮次，用于区分失败与沉默。 */
export function collectFailed(
  displays: readonly TurnDisplay[],
): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const display of displays) {
    for (const participant of display.participants) {
      if (participant.state === 'failed') ids.add(participant.characterId);
    }
  }
  return ids;
}
