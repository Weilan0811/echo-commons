import { useConfirmStage } from '@/api/authoring';
import type { InterviewAnswer } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { CandidatePanel } from '@/components/authoring/CandidatePanel';
import { StageBadge, StepActionBar, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import {
  canConfirmInterview,
  interviewBasisState,
  interviewLimits,
  interviewState,
} from '@/lib/authoring';
import { useDraftEditor } from '../useDraftEditor';
import type { StepProps } from './StepProps';

/** 拒答与记不清都是有效回答；短句插入后仍可继续编辑。 */
const REFUSAL_PHRASE = '这个我不太想说。';
const FORGOT_PHRASE = '记不清了。';

/**
 * 第三章：人物采访。
 *
 * 选题是十五题的子集（十到十五题），保存为 content.interview 快照；作答可以
 * 手写，也可以按一至五题一批让灵感代入角色回答。采访依据失效与阶段待复核是
 * 两回事：前者只在本章出现，并指向「重新确认来历 / 审核正文」两个动作。
 */
export function InterviewStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmStage(playerId, draftId, 'interview');
  const limits = interviewLimits(template);

  const workflow = draft.workflow;
  const status = workflow.interview;
  const state = interviewState(editor.form, limits);
  const basisState = interviewBasisState(workflow, editor.form);
  const accepted = status === 'accepted';

  // 生成候选要求选题已经保存，否则题目编号与服务端草稿对不上。
  const generationBlocked = editor.dirty || basisState === 'stale';
  const canConfirm =
    !editor.dirty
    && canConfirmInterview(workflow, draft.content, limits)
    && !confirm.isPending;

  const selectedIds = new Set(editor.form.interview.map((item) => item.question_id));

  const toggleQuestion = (questionId: string, question: string) => {
    if (selectedIds.has(questionId)) {
      if (!state.canDeselect) return;
      editor.patch({ interview: editor.form.interview.filter((item) => item.question_id !== questionId) });
      return;
    }
    if (state.selected >= limits.maximum) return;
    const next = [...editor.form.interview, { question_id: questionId, question, answer: '' }];
    editor.patch({ interview: sortByTemplate(next, template.interview.map((item) => item.id)) });
  };

  const setAnswer = (questionId: string, answer: string) => {
    editor.patch({
      interview: editor.form.interview.map((item) =>
        item.question_id === questionId ? { ...item, answer } : item,
      ),
    });
  };

  const quickFill = (questionId: string, phrase: string) => {
    const target = editor.form.interview.find((item) => item.question_id === questionId);
    if (target !== undefined && target.answer.trim() === '') setAnswer(questionId, phrase);
  };

  const clearInterview = () => {
    if (!window.confirm('清空全部选题与回答？本章将留白，采访依据也会失效。')) return;
    void editor.save({ ...editor.form, interview: [] });
  };

  const batches = chunk(editor.form.interview, limits.batch);

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      <StepHeader
        index={2}
        title="对谈"
        description="从十五个问题里保留十到十五题。可以逐题手写，也可以让灵感代入 TA 的语气分批回答；拒答或说记不清同样是有效回答。"
      >
        <StageBadge status={status} />
      </StepHeader>

      {status === 'review_required' ? (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-[11px] leading-relaxed text-warn">
          上游材料有改动，采访需要重新过目：请按「初识 → 来历 → 对谈」的顺序重新确认，再定稿本章。
        </div>
      ) : null}

      {basisState === 'stale' ? (
        <div className="rounded-lg border border-danger/40 bg-danger/10 px-3.5 py-3 text-[11px] leading-relaxed text-danger">
          <p className="font-semibold">采访依据已失效</p>
          <p className="mt-1">
            基础设定、名字或故事发生了变化，后续回答需要先重新确认前置设定。请先重新确认「来历」，
            并到「定格」章审核三份正文，再回来继续对谈。
          </p>
          <div className="mt-2 flex gap-3">
            <button type="button" onClick={() => onNavigate('story')} className="underline">
              去重新确认来历
            </button>
            <button type="button" onClick={() => onNavigate('final')} className="underline">
              去审核正文
            </button>
          </div>
        </div>
      ) : null}

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        <ZoneHeading
          title="选择问题"
          hint={`保留 ${limits.minimum}～${limits.maximum} 题 · 已选 ${state.selected} · 已答 ${state.answered}`}
        />
        <ul className="grid gap-2 sm:grid-cols-2">
          {template.interview.map((question) => {
            const selected = selectedIds.has(question.id);
            const answered = editor.form.interview.find((item) => item.question_id === question.id)?.answer.trim() !== '';
            const toggleAllowed = selected ? state.canDeselect : state.selected < limits.maximum;
            return (
              <li key={question.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  disabled={!toggleAllowed}
                  onClick={() => toggleQuestion(question.id, question.question)}
                  className={`flex h-full w-full flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors disabled:opacity-50 ${
                    selected
                      ? 'border-accent/60 bg-accent-soft/50'
                      : 'border-border-subtle bg-surface-sunken/50 hover:border-accent/40'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
                      {question.theme}
                    </span>
                    <span className="flex items-center gap-1.5 text-[10px]">
                      {answered ? <span className="text-ok">已答</span> : null}
                      <span className={selected ? 'text-accent' : 'text-content-faint'}>
                        {selected ? '✓ 保留' : '＋ 加入'}
                      </span>
                    </span>
                  </span>
                  <span className="text-[12px] leading-relaxed text-content-muted">{question.question}</span>
                </button>
              </li>
            );
          })}
        </ul>
        {!state.selectionComplete && state.selected > 0 ? (
          <p className="mt-2 text-[10px] text-warn">
            至少保留 {limits.minimum} 题（现在 {state.selected} 题），最多 {limits.maximum} 题。
          </p>
        ) : null}
      </div>

      {editor.form.interview.length > 0 ? (
        <div className="rounded-card border border-border-subtle bg-surface p-4">
          <ZoneHeading title="作者原稿 · 采访回答" hint="每批最多五题交给灵感，也可以全部手写" />
          <ul className="flex flex-col gap-3">
            {editor.form.interview.map((item) => (
              <AnswerEditor
                key={item.question_id}
                item={item}
                limit={limits.answerChars}
                onChange={(answer) => setAnswer(item.question_id, answer)}
                onRefuse={() => quickFill(item.question_id, REFUSAL_PHRASE)}
                onForgot={() => quickFill(item.question_id, FORGOT_PHRASE)}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {batches.map((batch, index) => (
        <CandidatePanel
          key={batch.map((item) => item.question_id).join('|')}
          draft={draft}
          playerId={playerId}
          operation="interview"
          operationHint={`${template.operations.interview ?? ''}（第 ${index + 1} 批，共 ${batch.length} 题）`}
          canGenerate={!generationBlocked}
          generateHint={
            basisState === 'stale'
              ? '采访依据已失效，请先重新确认来历并审核正文。'
              : '选题有未保存的调整，先保存后再请 TA 回答。'
          }
          questionIds={batch.map((item) => item.question_id)}
        />
      ))}

      {editor.conflict ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新，已重新载入最新内容，请在最新版本上继续。
        </p>
      ) : null}
      {editor.saveError !== null ? <ErrorNotice error={editor.saveError} /> : null}
      {confirm.isError ? <p className="text-[11px] text-danger">{errorMessage(confirm.error)}</p> : null}

      <StepActionBar>
        <button
          type="button"
          disabled={!editor.dirty || editor.isSaving}
          onClick={() => void editor.save()}
          className="rounded-lg border border-border-strong px-3.5 py-1.5 text-[12px] text-content-muted transition-colors hover:border-accent/60 hover:text-content disabled:opacity-40"
        >
          {editor.isSaving ? '保存中…' : '保存选题与回答'}
        </button>
        {editor.dirty ? <span className="text-[10px] text-content-faint">先保存，再生成回答或确认本章</span> : null}
        {state.selectionComplete ? (
          <button
            type="button"
            onClick={clearInterview}
            className="text-[11px] text-content-faint transition-colors hover:text-danger"
          >
            清空采访，本章留白
          </button>
        ) : null}

        <div className="ml-auto flex items-center gap-3">
          {accepted ? (
            <button
              type="button"
              onClick={() => onNavigate('final')}
              className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110"
            >
              继续：定格 →
            </button>
          ) : (
            <>
              {!state.selectionComplete ? (
                <span className="text-[10px] text-content-faint">
                  保留 {limits.minimum}～{limits.maximum} 题
                </span>
              ) : state.answered < state.selected ? (
                <span className="text-[10px] text-content-faint">
                  还有 {state.selected - state.answered} 题没有回答（拒答也可以）
                </span>
              ) : null}
              <button
                type="button"
                disabled={!canConfirm}
                onClick={() => void confirm.mutateAsync(draft.revision).catch(() => undefined)}
                className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
              >
                {confirm.isPending ? '确认中…' : '确认人物采访'}
              </button>
            </>
          )}
        </div>
      </StepActionBar>
    </div>
  );
}

function AnswerEditor({
  item,
  limit,
  onChange,
  onRefuse,
  onForgot,
}: {
  readonly item: InterviewAnswer;
  readonly limit: number;
  readonly onChange: (answer: string) => void;
  readonly onRefuse: () => void;
  readonly onForgot: () => void;
}) {
  return (
    <li className="rounded-lg border border-border-subtle bg-surface-overlay/50 p-3">
      <p className="text-[12px] font-medium text-content">{item.question}</p>
      <textarea
        value={item.answer}
        maxLength={limit}
        rows={3}
        onChange={(event) => onChange(event.target.value)}
        placeholder="TA 会怎样回答？可以先空着，等灵感起草，也可以点下面的快捷回应。"
        className="mt-2 w-full resize-y rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
      />
      <div className="mt-1.5 flex items-center justify-between">
        <span className="flex gap-2">
          <button
            type="button"
            onClick={onRefuse}
            className="rounded border border-border-subtle px-2 py-0.5 text-[10px] text-content-faint hover:border-warn/50 hover:text-warn"
          >
            拒答
          </button>
          <button
            type="button"
            onClick={onForgot}
            className="rounded border border-border-subtle px-2 py-0.5 text-[10px] text-content-faint hover:border-accent/50 hover:text-accent"
          >
            记不清
          </button>
        </span>
        <span className="tabular text-[10px] text-content-faint">{item.answer.length}/{limit}</span>
      </div>
    </li>
  );
}

/** 选题按模板题目顺序排列，批次顺序因此稳定。 */
function sortByTemplate(items: readonly InterviewAnswer[], templateOrder: readonly string[]): InterviewAnswer[] {
  const rank = new Map(templateOrder.map((id, index) => [id, index]));
  return [...items].sort((a, b) => (rank.get(a.question_id) ?? 0) - (rank.get(b.question_id) ?? 0));
}

function chunk<T>(items: readonly T[], size: number): readonly (readonly T[])[] {
  if (size <= 0) return items.length === 0 ? [] : [items];
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    result.push(items.slice(index, index + size));
  }
  return result;
}
