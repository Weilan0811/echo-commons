import { useState } from 'react';
import { useConfirmStage } from '@/api/authoring';
import type { InterviewAnswer } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { InterviewInspirationPanel } from '@/components/authoring/InterviewInspirationPanel';
import { InspirationDrawer } from '@/components/authoring/InspirationDrawer';
import { StageBadge, StepActionBar, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import { canConfirmInterview, interviewLimits, interviewState } from '@/lib/authoring';
import { useDraftEditor } from '../useDraftEditor';
import type { StepProps } from './StepProps';

/** 拒答与记不清都是有效回答；短句插入后仍可继续编辑。 */
const REFUSAL_PHRASE = '这个我不太想说。';
const FORGOT_PHRASE = '记不清了。';

/**
 * 第三章：人物采访。
 *
 * 选题采用「默认十五题删减」：第一次进入从模板的十五题开始，移除零到五题，
 * 暂存后锁定，「再次编辑」才能调整；回答在核对态只读。全章只有一个 AI
 * 模块，自动按五题一批生成并接受未回答的问题。采访依据相关提示只出现在
 * 该模块内，手写流程不受打扰。
 */
export function InterviewStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmStage(playerId, draftId, 'interview');
  const limits = interviewLimits(template);
  const [runRunning, setRunRunning] = useState(false);

  const workflow = draft.workflow;
  const status = workflow.interview;
  const editing = editor.editing;
  const state = interviewState(editor.form, limits);
  const accepted = status === 'accepted';
  const savedEmpty = draft.content.interview.length === 0;

  const canConfirm =
    !editing
    && canConfirmInterview(workflow, draft.content, limits)
    && !confirm.isPending;

  const selectedIds = new Set(editor.form.interview.map((item) => item.question_id));

  const beginSelection = () => {
    editor.startEdit();
    // 默认保留全部十五题，作者只做删减，而不是从零逐个添加。
    editor.patch({ interview: template.interview.map((item) => ({ question_id: item.id, question: item.question, answer: '' })) });
  };

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
    if (!window.confirm('清空全部选题与回答？本章将留白，已生成的采访依据也会作废。')) return;
    void editor.save({ ...editor.form, interview: [] });
  };

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      <StepHeader
        index={2}
        title="对谈"
        description="从十五个问题里删减保留十到十五题。可以逐题手写，也可以让灵感代入 TA 的语气一次答完全章；拒答或说记不清同样是有效回答。"
      >
        <div className="flex items-center gap-2">
          {/* 按当前编辑表单判断：刚选题未暂存时按钮也要在，面板内以 locked 提示先暂存。 */}
          {editor.form.interview.length > 0 ? (
            <InspirationDrawer label="灵感代答">
              <InterviewInspirationPanel
                playerId={playerId}
                draftId={draftId}
                draft={draft}
                template={template}
                locked={editing}
                onRunningChange={setRunRunning}
              />
            </InspirationDrawer>
          ) : null}
          <StageBadge status={status} />
        </div>
      </StepHeader>

      {status === 'review_required' ? (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-[11px] leading-relaxed text-warn">
          上游材料有改动，采访需要重新过目：请按「初识 → 来历 → 对谈」的顺序重新确认，再定稿本章。
        </div>
      ) : null}

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        <ZoneHeading
          title="选择问题"
          hint={
            editing
              ? `删减保留 ${limits.minimum}～${limits.maximum} 题 · 当前 ${state.selected} 题`
              : `已保留 ${state.selected} 题 · 已答 ${state.answered}`
          }
        />
        {savedEmpty && !editing ? (
          <div className="flex flex-col items-start gap-2 py-2">
            <p className="text-[12px] leading-relaxed text-content-muted">
              本章可以留白，也可以从默认的十五个问题开始，删掉不想问的题后逐题对谈。
            </p>
            <button
              type="button"
              onClick={beginSelection}
              className="rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] font-medium text-accent hover:bg-accent/20"
            >
              开始选择问题（默认十五题）
            </button>
          </div>
        ) : (
          <>
            <ul className="grid gap-2 sm:grid-cols-2">
              {template.interview.map((question) => {
                const selected = selectedIds.has(question.id);
                // 未选的题在 form 里没有记录，find 返回 undefined；
                // 空值合并不能省，否则 undefined !== '' 会把未选误判成已答。
                const answered =
                  (editor.form.interview.find((item) => item.question_id === question.id)?.answer.trim() ?? '') !== '';
                const toggleAllowed = editing && (selected ? state.canDeselect : state.selected < limits.maximum);
                return (
                  <li key={question.id}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      disabled={!toggleAllowed}
                      onClick={() => toggleQuestion(question.id, question.question)}
                      className={`flex h-full w-full flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors disabled:cursor-default ${
                        selected
                          ? 'border-accent/60 bg-accent-soft/50'
                          : 'border-border-subtle bg-surface-sunken/50'
                      } ${editing ? 'hover:border-accent/40 disabled:opacity-50' : 'opacity-80'}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
                          {question.theme}
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px]">
                          {answered ? <span className="text-ok">已答</span> : null}
                          {selected ? (
                            <span className="text-accent">{editing ? '✓ 保留' : '已保留'}</span>
                          ) : editing ? (
                            <span className="text-content-faint">移除</span>
                          ) : (
                            <span className="text-content-faint">未选</span>
                          )}
                        </span>
                      </span>
                      <span className="text-[12px] leading-relaxed text-content-muted">{question.question}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {editing && state.selected > 0 && !state.selectionComplete ? (
              <p className="mt-2 text-[10px] text-warn">
                至少保留 {limits.minimum} 题（现在 {state.selected} 题）。
              </p>
            ) : null}
          </>
        )}
      </div>

      {editor.form.interview.length > 0 ? (
        <div className="rounded-card border border-border-subtle bg-surface p-4">
          <ZoneHeading
            title="作者原稿 · 采访回答"
            hint={editing ? '编辑中：暂存后会重新锁定' : '已锁定，点下方「再次编辑」修改'}
          />
          <ul className="flex flex-col gap-3">
            {editor.form.interview.map((item) =>
              editing ? (
                <AnswerEditor
                  key={item.question_id}
                  item={item}
                  limit={limits.answerChars}
                  onChange={(answer) => setAnswer(item.question_id, answer)}
                  onRefuse={() => quickFill(item.question_id, REFUSAL_PHRASE)}
                  onForgot={() => quickFill(item.question_id, FORGOT_PHRASE)}
                />
              ) : (
                <AnswerView key={item.question_id} item={item} />
              ),
            )}
          </ul>
        </div>
      ) : null}

      {editor.conflict ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新（比如刚接受了一批回答），已重新载入最新内容，请在最新版本上继续。
        </p>
      ) : null}
      {editor.saveError !== null ? <ErrorNotice error={editor.saveError} /> : null}
      {confirm.isError ? <p className="text-[11px] text-danger">{errorMessage(confirm.error)}</p> : null}

      <StepActionBar>
        {editing ? (
          <>
            <button
              type="button"
              disabled={!editor.dirty || editor.isSaving}
              onClick={() => void editor.save()}
              className="rounded-lg border border-border-strong px-3.5 py-1.5 text-[12px] text-content transition-colors hover:border-accent/60 disabled:opacity-40"
            >
              {editor.isSaving ? '暂存中…' : '暂存本章'}
            </button>
            <button
              type="button"
              disabled={editor.isSaving}
              onClick={editor.cancelEdit}
              className="text-[12px] text-content-faint transition-colors hover:text-content-muted disabled:opacity-40"
            >
              放弃修改
            </button>
            <span className="ml-auto text-[10px] text-content-faint">暂存后回到核对，再生成回答或确认本章</span>
          </>
        ) : (
          <>
            {draft.content.interview.length > 0 ? (
              <button
                type="button"
                disabled={runRunning}
                onClick={editor.startEdit}
                className="rounded-lg border border-border-strong px-3.5 py-1.5 text-[12px] text-content-muted transition-colors hover:border-accent/60 hover:text-content disabled:opacity-40"
              >
                再次编辑
              </button>
            ) : null}
            {state.selectionComplete ? (
              <button
                type="button"
                disabled={runRunning}
                onClick={clearInterview}
                className="text-[11px] text-content-faint transition-colors hover:text-danger disabled:opacity-40"
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
              ) : state.selected === 0 ? (
                <button
                  type="button"
                  onClick={() => onNavigate('final')}
                  className="text-[12px] text-content-faint transition-colors hover:text-content"
                >
                  本章留白，直接去定格 →
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
                  ) : !canConfirmStoryAccepted(workflow) ? (
                    <span className="text-[10px] text-content-faint">先确认基础人设和来历，才能定稿采访</span>
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
          </>
        )}
      </StepActionBar>
    </div>
  );
}

/** 对谈章右侧动作条用的最小前置提示，对齐 canConfirmInterview 的门控。 */
function canConfirmStoryAccepted(workflow: StepProps['draft']['workflow']): boolean {
  return workflow.basic === 'accepted' && workflow.story === 'accepted';
}

function AnswerView({ item }: { readonly item: InterviewAnswer }) {
  return (
    <li className="rounded-lg border border-border-subtle bg-surface-overlay/50 p-3">
      <p className="text-[12px] font-medium text-content">{item.question}</p>
      <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-content-muted">
        {item.answer.trim() === '' ? (
          <span className="text-content-faint">（尚未回答）</span>
        ) : (
          item.answer
        )}
      </p>
    </li>
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
        placeholder="TA 会怎样回答？可以先空着，让灵感代答，也可以点下面的快捷回应。"
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
