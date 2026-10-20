// 自定义人物创作的纯推导。
//
// 阶段门控以后端 domain.authoring 的规则为准（基础先确认；采访要求故事已确认
// 且非空；定稿要求已使用阶段均已确认且正文已审核）。组件只消费这里的结果，
// 后端 409 仍是最终权威，因此这些函数只用于「提前禁用与说明」，不替代报错处理。
import type { SchemaOf } from '@/api/http';

type Draft = SchemaOf<'DraftView'>;
type Candidate = SchemaOf<'CandidateView'>;
type Workflow = SchemaOf<'AuthoringWorkflow'>;
type Content = SchemaOf<'AuthoringContent'>;
type StageStatus = Workflow['basic'];

export type AuthoringChapter = 'basic' | 'story' | 'interview' | 'final';

export interface ChapterMeta {
  readonly id: AuthoringChapter;
  readonly index: number;
  readonly title: string;
  readonly subtitle: string;
}

/** 章节顺序与对外文案。向导各处统一从这里取，避免标题漂移。 */
export const CHAPTERS: readonly ChapterMeta[] = [
  { id: 'basic', index: 0, title: '初识', subtitle: '基础人设' },
  { id: 'story', index: 1, title: '来历', subtitle: '过去故事' },
  { id: 'interview', index: 2, title: '对谈', subtitle: '人物采访' },
  { id: 'final', index: 3, title: '定格', subtitle: '确认与入住' },
];

export const STAGE_LABEL: Readonly<Record<Exclude<AuthoringChapter, 'final'>, string>> = {
  basic: '基础人设',
  story: '过去故事',
  interview: '人物采访',
};

/** 章节指示器四态文案。unused 表示作者主动留白。 */
export function stageStatusLabel(status: StageStatus): string {
  switch (status) {
    case 'accepted':
      return '已定稿';
    case 'review_required':
      return '待复核';
    case 'unused':
      return '留白';
    default:
      return '未完成';
  }
}

export function hasStory(content: Content): boolean {
  return content.story.trim() !== '' || (content.relationships?.length ?? 0) > 0;
}

/**
 * 章节是否允许进入。
 *
 * 严格按顺序解锁；已经展开过的章节在上游被改回待复核时仍可进入，否则作者
 * 无法完成复核动作。采访章额外要求故事已定稿，或采访本身已经开始。
 */
export function canAccessChapter(workflow: Workflow, content: Content, chapter: AuthoringChapter): boolean {
  switch (chapter) {
    case 'basic':
      return true;
    case 'story':
      return workflow.basic === 'accepted' || workflow.story !== 'unused';
    case 'interview':
      return (
        (workflow.story === 'accepted' && hasStory(content))
        || workflow.interview === 'accepted'
        || workflow.interview === 'review_required'
      );
    case 'final':
      return workflow.basic === 'accepted';
  }
}

/** 故事章能否确认：基础已定稿且故事非空。 */
export function canConfirmStory(workflow: Workflow, content: Content): boolean {
  return workflow.basic === 'accepted' && hasStory(content);
}

export interface InterviewLimits {
  readonly maximum: number;
  readonly minimum: number;
  readonly batch: number;
  readonly answerChars: number;
}

export function interviewLimits(template: { readonly limits: Record<string, number> }): InterviewLimits {
  // 这些键由后端模板固定提供（authoring 模板装配处写入），缺项只可能来自
  // 契约外的异常响应；回退 0 会让所有选题校验失败并阻断流程，不静默放行。
  const limits = template.limits;
  return {
    maximum: limits.interview_answers ?? 0,
    minimum: limits.interview_minimum ?? 0,
    batch: limits.interview_batch ?? 0,
    answerChars: limits.answer ?? 0,
  };
}

export interface InterviewState {
  readonly selected: number;
  readonly answered: number;
  readonly minimum: number;
  readonly maximum: number;
  /** 选题数量在约定区间。 */
  readonly selectionComplete: boolean;
  /** 选题合法且全部有回答（拒答同样有效）。 */
  readonly allAnswered: boolean;
  readonly canConfirm: boolean;
  /** 还能否再取消一题。 */
  readonly canDeselect: boolean;
  readonly unansweredIds: readonly string[];
}

export function interviewState(
  content: Content,
  limits: Pick<InterviewLimits, 'maximum' | 'minimum'>,
): InterviewState {
  const selected = content.interview.length;
  const unansweredIds = content.interview
    .filter((item) => item.answer.trim() === '')
    .map((item) => item.question_id);
  const selectionComplete = selected >= limits.minimum && selected <= limits.maximum;
  return {
    selected,
    answered: selected - unansweredIds.length,
    minimum: limits.minimum,
    maximum: limits.maximum,
    selectionComplete,
    allAnswered: selectionComplete && unansweredIds.length === 0,
    canConfirm: selectionComplete && unansweredIds.length === 0,
    canDeselect: selected > limits.minimum,
    unansweredIds,
  };
}

/** 采访章能否确认，对齐后端 require + completed 两段校验。 */
export function canConfirmInterview(
  workflow: Workflow,
  content: Content,
  limits: Pick<InterviewLimits, 'maximum' | 'minimum'>,
): boolean {
  return canConfirmStory(workflow, content) && interviewState(content, limits).canConfirm;
}

/**
 * 采访依据状态。
 *
 * - none：还没有选题，不显示依据相关提示；
 * - active：依据存在，后续批次沿用；
 * - stale：选题存在但依据被上游修改清除，且前置条件尚未恢复，需要作者重新
 *   确认故事/正文；恢复后下一批采访候选会由后端重新建立依据（ready）。
 */
export type InterviewBasisState = 'none' | 'active' | 'ready' | 'stale';

export function interviewBasisState(workflow: Workflow, content: Content): InterviewBasisState {
  if (content.interview.length === 0) return 'none';
  if (workflow.interview_basis !== null && workflow.interview_basis !== undefined) return 'active';
  const prerequisitesReady =
    workflow.basic === 'accepted'
    && workflow.story === 'accepted'
    && hasStory(content)
    && workflow.documents_review === 'accepted';
  return prerequisitesReady ? 'ready' : 'stale';
}

/** 校准候选的前置：已使用阶段均已确认（不要求正文已审核）。 */
export function canCalibrate(workflow: Workflow, content: Content): boolean {
  if (workflow.basic !== 'accepted') return false;
  if (hasStory(content) && workflow.story !== 'accepted') return false;
  if (content.interview.length > 0 && workflow.interview !== 'accepted') return false;
  return true;
}

/** 最终固定条件：基础已定稿、已使用阶段均已定稿、三份正文已审核。 */
export function canFinalize(workflow: Workflow, content: Content): boolean {
  if (workflow.basic !== 'accepted') return false;
  if (hasStory(content) && workflow.story !== 'accepted') return false;
  if (content.interview.length > 0 && workflow.interview !== 'accepted') return false;
  return workflow.documents_review === 'accepted';
}

/** 定稿尚缺的事项，用于终章逐项说明。 */
export function finalizeBlockers(
  workflow: Workflow,
  content: Content,
  limits: Pick<InterviewLimits, 'maximum' | 'minimum'>,
): readonly string[] {
  const blockers: string[] = [];
  if (workflow.basic !== 'accepted') blockers.push('确认基础人设');
  if (hasStory(content) && workflow.story !== 'accepted') blockers.push('确认过去故事');
  if (content.interview.length > 0) {
    if (workflow.interview !== 'accepted') {
      blockers.push(interviewState(content, limits).selectionComplete
        ? '完成并确认人物采访'
        : '采访选题需保留十至十五题');
    }
  }
  if (workflow.documents_review !== 'accepted') blockers.push('审核三份运行正文');
  return blockers;
}

/**
 * 候选是否已过期：候选依据的草稿版本早于当前版本。
 * 由前端比较得出，不依赖后端错误码；过期候选可读不可接受。
 */
export function isCandidateStale(candidate: Candidate, draft: Draft): boolean {
  return candidate.input_revision < draft.revision;
}

export type CandidateClockState = 'running' | 'confirming' | 'finished';

export interface CandidateClock {
  readonly state: CandidateClockState;
  /** running 时的剩余毫秒，其他状态为 0。 */
  readonly remainingMs: number;
}

/**
 * 候选期限时钟。
 *
 * 本地时间超过 deadline 但后端仍是 processing 时，进入 confirming：
 * 超期标记发生在后端下一次读取时，界面不能提前宣布失败。
 */
export function candidateClock(candidate: Candidate, nowMs: number): CandidateClock {
  if (candidate.status !== 'processing') return { state: 'finished', remainingMs: 0 };
  const deadlineMs = Date.parse(candidate.deadline_utc);
  if (Number.isNaN(deadlineMs)) return { state: 'confirming', remainingMs: 0 };
  const remainingMs = deadlineMs - nowMs;
  return remainingMs > 0
    ? { state: 'running', remainingMs }
    : { state: 'confirming', remainingMs: 0 };
}

/** 接受候选按钮文案：按操作范围说明这次接受会更新什么。 */
export const OPERATION_SCOPE: Readonly<Record<Candidate['operation'], string>> = {
  basic: '接受并更新描述与三份正文',
  story: '接受并更新故事原文',
  interview: '接受并更新本批回答',
  calibrate: '接受并更新三份正文',
};

/** 校准有冲突时后端拒绝接受，界面直接禁用。 */
export function candidateHasConflicts(candidate: Candidate): boolean {
  if (candidate.operation !== 'calibrate' || candidate.output === null) return false;
  if (candidate.output.operation !== 'calibrate') return false;
  return candidate.output.conflicts.length > 0;
}

/** 三份正文审核状态的一行提示文案。 */
export function documentsReviewText(workflow: Workflow): string {
  return workflow.documents_review === 'accepted'
    ? '三份运行正文已审核，与当前材料一致'
    : '三份运行正文待审核：后续材料变化后需要重新确认';
}
