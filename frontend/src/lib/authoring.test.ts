import { describe, expect, it } from 'vitest';
import type { SchemaOf } from '@/api/http';
import {
  canAccessChapter,
  canCalibrate,
  canConfirmInterview,
  canConfirmStory,
  canFinalize,
  candidateClock,
  documentsReviewText,
  finalizeBlockers,
  interviewBasisState,
  interviewState,
  isCandidateStale,
} from './authoring';

type Workflow = SchemaOf<'AuthoringWorkflow'>;
type Content = SchemaOf<'AuthoringContent'>;
type Draft = SchemaOf<'DraftView'>;
type Candidate = SchemaOf<'CandidateView'>;

const LIMITS = { maximum: 15, minimum: 10 } as const;

function content(overrides: Partial<Content> = {}): Content {
  return {
    profile: '你叫阿岚。',
    voice: '自然说话',
    relational_dynamics: '慢慢认识对方',
    display_name: '阿岚',
    description: '一个守夜人',
    story: '',
    interview: [],
    ...overrides,
  };
}

function workflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    basic: 'pending',
    story: 'unused',
    interview: 'unused',
    documents_review: 'review_required',
    interview_basis: null,
    ...overrides,
  };
}

function answer(questionId: string, value = '') {
  return { question_id: questionId, question: questionId, answer: value };
}

function selected(count: number, answeredUntil = 0): Content['interview'] {
  return Array.from({ length: count }, (_unused, index) =>
    answer(`q${index + 1}`, index < answeredUntil ? '回答' : ''),
  );
}

function draft(overrides: Partial<Draft> = {}): Draft {
  return {
    draft_id: '11111111-1111-1111-1111-111111111111',
    owner_player_id: 'player-a',
    status: 'draft',
    revision: 3,
    content: content(),
    workflow: workflow(),
    confirmed_blueprint_id: null,
    accepted_candidate_id: null,
    material_processing: 'stored_only',
    created_at_utc: '2026-10-01T00:00:00Z',
    updated_at_utc: '2026-10-02T00:00:00Z',
    ...overrides,
  };
}

function candidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    candidate_id: '22222222-2222-2222-2222-222222222222',
    draft_id: draft().draft_id,
    input_revision: 3,
    operation: 'basic',
    status: 'completed',
    error_code: null,
    model_profile: 'test-profile',
    model_requests: 1,
    usage: {},
    output: null,
    frozen_input: {},
    deadline_utc: '2026-10-08T12:01:30Z',
    created_at_utc: '2026-10-08T12:00:00Z',
    finished_at_utc: null,
    ...overrides,
  };
}

describe('章节可达性', () => {
  it('新草稿只能进入基础章', () => {
    const wf = workflow();
    const c = content();
    expect(canAccessChapter(wf, c, 'basic')).toBe(true);
    expect(canAccessChapter(wf, c, 'story')).toBe(false);
    expect(canAccessChapter(wf, c, 'interview')).toBe(false);
    expect(canAccessChapter(wf, c, 'final')).toBe(false);
  });

  it('基础确认后解锁故事与定格，但采访仍锁定', () => {
    const wf = workflow({ basic: 'accepted', documents_review: 'accepted' });
    const c = content();
    expect(canAccessChapter(wf, c, 'story')).toBe(true);
    expect(canAccessChapter(wf, c, 'interview')).toBe(false);
    expect(canAccessChapter(wf, c, 'final')).toBe(true);
  });

  it('采访只在故事确认且非空后解锁；留白故事不能采访', () => {
    const wf = workflow({ basic: 'accepted', story: 'accepted', documents_review: 'accepted' });
    expect(canAccessChapter(wf, content({ story: '  ' }), 'interview')).toBe(false);
    expect(canAccessChapter(wf, content({ story: '一段经历' }), 'interview')).toBe(true);
  });

  it('已开始的采访在上游待复核时仍可进入以便完成复核', () => {
    const wf = workflow({
      basic: 'review_required',
      story: 'review_required',
      interview: 'review_required',
    });
    const c = content({ story: '一段经历', interview: selected(10, 10) });
    expect(canAccessChapter(wf, c, 'interview')).toBe(true);
  });
});

describe('阶段确认条件', () => {
  it('故事确认要求基础已定稿且故事非空', () => {
    expect(canConfirmStory(workflow({ basic: 'accepted' }), content({ story: '经历' }))).toBe(true);
    expect(canConfirmStory(workflow({ basic: 'pending' }), content({ story: '经历' }))).toBe(false);
    expect(canConfirmStory(workflow({ basic: 'accepted' }), content({ story: '   ' }))).toBe(false);
  });

  it('采访确认要求故事已定稿、选题 10～15 且全部有回答', () => {
    const ready = workflow({ basic: 'accepted', story: 'accepted' });
    expect(canConfirmInterview(ready, content({ story: 's', interview: selected(9, 9) }), LIMITS)).toBe(false);
    expect(canConfirmInterview(ready, content({ story: 's', interview: selected(10, 9) }), LIMITS)).toBe(false);
    expect(canConfirmInterview(ready, content({ story: 's', interview: selected(15, 15) }), LIMITS)).toBe(true);
    expect(canConfirmInterview(ready, content({ story: 's', interview: selected(16, 16) }), LIMITS)).toBe(false);
  });
});

describe('interviewState', () => {
  it('统计已答数量并在达到下限前禁止继续取消', () => {
    const state = interviewState(content({ interview: selected(12, 7) }), LIMITS);
    expect(state.selected).toBe(12);
    expect(state.answered).toBe(7);
    expect(state.canDeselect).toBe(true);
    expect(state.canConfirm).toBe(false);
    expect(state.unansweredIds).toHaveLength(5);
  });

  it('恰好十题时不能再取消', () => {
    expect(interviewState(content({ interview: selected(10, 10) }), LIMITS).canDeselect).toBe(false);
  });

  it('空白回答与拒答（非空）被区分对待', () => {
    const c = content({ interview: [answer('a', '  '), answer('b', '这个我不想说。')] });
    const state = interviewState(c, { maximum: 2, minimum: 2 });
    expect(state.answered).toBe(1);
    expect(state.canConfirm).toBe(false);
  });
});

describe('采访依据', () => {
  it('未选题为 none，有依据为 active', () => {
    expect(interviewBasisState(workflow(), content())).toBe('none');
    const withBasis = workflow({ interview_basis: {
      profile: '', voice: '', relational_dynamics: '', agent_contract: '',
      expression_guidance: '', description: '', display_name: '', story: '',
    } });
    expect(interviewBasisState(withBasis, content({ interview: selected(10) }))).toBe('active');
  });

  it('依据被清除且前置未恢复为 stale；恢复后为 ready', () => {
    const broken = workflow({ basic: 'accepted', story: 'review_required' });
    expect(interviewBasisState(broken, content({ story: 's', interview: selected(10) }))).toBe('stale');
    const fixed = workflow({
      basic: 'accepted',
      story: 'accepted',
      documents_review: 'accepted',
    });
    expect(interviewBasisState(fixed, content({ story: 's', interview: selected(10) }))).toBe('ready');
  });
});

describe('校准与定稿', () => {
  it('校准要求已使用阶段均已确认，但不要求正文已审核', () => {
    const wf = workflow({
      basic: 'accepted',
      story: 'accepted',
      interview: 'accepted',
      documents_review: 'review_required',
    });
    const c = content({ story: 's', interview: selected(10, 10) });
    expect(canCalibrate(wf, c)).toBe(true);
  });

  it('定稿要求正文已审核，并列出缺口', () => {
    const wf = workflow({ basic: 'accepted', documents_review: 'review_required' });
    const c = content({ story: 's' });
    expect(canFinalize(wf, c)).toBe(false);
    expect(finalizeBlockers(wf, c, LIMITS)).toContain('确认过去故事');
    expect(finalizeBlockers(wf, c, LIMITS)).toContain('审核三份运行正文');

    const complete = workflow({
      basic: 'accepted',
      story: 'unused',
      interview: 'unused',
      documents_review: 'accepted',
    });
    expect(canFinalize(complete, content())).toBe(true);
  });
});

describe('候选过期与期限', () => {
  it('input_revision 小于当前草稿版本即为过期', () => {
    expect(isCandidateStale(candidate({ input_revision: 2 }), draft({ revision: 3 }))).toBe(true);
    expect(isCandidateStale(candidate({ input_revision: 3 }), draft({ revision: 3 }))).toBe(false);
  });

  it('期限内倒计时；归零后是 confirming 而不是失败', () => {
    const processing = candidate({ status: 'processing' });
    const running = candidateClock(processing, Date.parse('2026-10-08T12:01:00Z'));
    expect(running.state).toBe('running');
    expect(running.remainingMs).toBe(30_000);

    const confirming = candidateClock(processing, Date.parse('2026-10-08T12:01:31Z'));
    expect(confirming.state).toBe('confirming');
    expect(confirming.remainingMs).toBe(0);
  });

  it('已完成候选不再参与倒计时', () => {
    expect(candidateClock(candidate(), Date.now()).state).toBe('finished');
  });
});

describe('正文审核提示', () => {
  it('两种状态各有明确文案', () => {
    expect(documentsReviewText(workflow())).toContain('待审核');
    expect(documentsReviewText(workflow({ documents_review: 'accepted' }))).toContain('已审核');
  });
});
