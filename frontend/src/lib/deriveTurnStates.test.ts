import { describe, expect, it } from 'vitest';
import type { SchemaOf } from '@/api/http';
import {
  collectFailed,
  collectResponding,
  countActiveTurns,
  deriveTurnStates,
} from './deriveTurnStates';

type TurnView = SchemaOf<'TurnView'>;
type ParticipationView = SchemaOf<'ParticipationView'>;

function participation(overrides: Partial<ParticipationView>): ParticipationView {
  return {
    character_id: 'preview-jin',
    reason_code: 'selected',
    selection_order: 1,
    status: 'selected',
    outcome: null,
    ...overrides,
  } as ParticipationView;
}

function turn(overrides: Partial<TurnView>): TurnView {
  return {
    social_turn_id: 'turn-1',
    conversation_id: 'c1',
    status: 'running',
    created_at_utc: '2026-10-04T00:00:00Z',
    completed_at_utc: null,
    participation: [],
    ...overrides,
  } as TurnView;
}

describe('deriveTurnStates', () => {
  it('尚未执行的主动发言显示为等待发言', () => {
    const displays = deriveTurnStates([
      turn({ status: 'pending', participation: [participation({ status: 'selected' })] }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('waiting');
    expect(collectResponding(displays).size).toBe(0);
  });
  it('进行中的轮次里被选中的角色显示为正在回应', () => {
    const displays = deriveTurnStates([
      turn({ participation: [participation({ status: 'selected' })] }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('responding');
  });

  it('轮次结束后同一状态变为已完成', () => {
    const displays = deriveTurnStates([
      turn({ status: 'completed', participation: [participation({ status: 'selected' })] }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('completed');
  });

  it('outcome 为 silent 时按沉默处理，即使 status 是 completed', () => {
    // 契约说明被选择角色主动沉默记为 completed，outcome 为 silent。
    const displays = deriveTurnStates([
      turn({
        status: 'completed',
        participation: [participation({ status: 'completed', outcome: 'silent' })],
      }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('silent');
  });

  it('status 为 silent 时按沉默处理', () => {
    const displays = deriveTurnStates([
      turn({ status: 'completed', participation: [participation({ status: 'silent' })] }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('silent');
  });

  it('失败与沉默区分开', () => {
    const displays = deriveTurnStates([
      turn({
        status: 'completed',
        participation: [
          participation({ character_id: 'preview-jin', status: 'failed' }),
          participation({ character_id: 'preview-an', status: 'silent' }),
        ],
      }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('failed');
    expect(displays[0]?.participants[1]?.state).toBe('silent');
  });

  it('取消独立展示，不并入失败', () => {
    const displays = deriveTurnStates([
      turn({ participation: [participation({ status: 'cancelled' })] }),
    ]);
    expect(displays[0]?.participants[0]?.state).toBe('cancelled');
  });

  it('轮次完成且没有角色消息时不产生异常状态', () => {
    const displays = deriveTurnStates([turn({ status: 'completed', participation: [] })]);
    expect(displays[0]?.participants).toEqual([]);
  });

  it('保留规划选择次序，但界面不据此排序', () => {
    const displays = deriveTurnStates([
      turn({
        participation: [
          participation({ character_id: 'preview-an', selection_order: 2 }),
          participation({ character_id: 'preview-jin', selection_order: 1 }),
        ],
      }),
    ]);
    expect(displays[0]?.participants[0]?.selectionOrder).toBe(2);
    expect(displays[0]?.participants[1]?.selectionOrder).toBe(1);
  });

  it('空输入返回空数组', () => {
    expect(deriveTurnStates([])).toEqual([]);
  });
});

describe('countActiveTurns', () => {
  it('只统计进行中的轮次', () => {
    const turns = [
      turn({ social_turn_id: 'a', status: 'running' }),
      turn({ social_turn_id: 'b', status: 'completed' }),
      turn({ social_turn_id: 'c', status: 'running' }),
    ];
    expect(countActiveTurns(turns)).toBe(2);
  });

  it('没有进行中轮次时为零', () => {
    expect(countActiveTurns([turn({ status: 'completed' })])).toBe(0);
  });
});

describe('collectResponding', () => {
  it('收集正在回应的角色，不包含已完成与沉默', () => {
    const displays = deriveTurnStates([
      turn({
        status: 'running',
        participation: [
          participation({ character_id: 'preview-jin', status: 'selected' }),
          participation({ character_id: 'preview-an', status: 'silent' }),
        ],
      }),
    ]);
    expect([...collectResponding(displays)]).toEqual(['preview-jin']);
  });

  it('没有正在回应的角色时为空', () => {
    expect(collectResponding(deriveTurnStates([turn({ status: 'completed' })])).size).toBe(0);
  });
});

describe('collectFailed', () => {
  it('只收集失败角色，便于与沉默区分', () => {
    const displays = deriveTurnStates([
      turn({
        status: 'completed',
        participation: [
          participation({ character_id: 'preview-jin', status: 'failed' }),
          participation({ character_id: 'preview-an', outcome: 'silent', status: 'completed' }),
        ],
      }),
    ]);
    expect([...collectFailed(displays)]).toEqual(['preview-jin']);
  });
});
