import { useEffect, useState } from 'react';
import {
  useConfirmDocuments,
  type AuthoringDraft,
  type AuthoringTemplate,
} from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { DocumentSheets } from './DocumentSheets';
import { useInterviewAnswersRun } from '@/app/pages/authoring/useInterviewAnswersRun';
import { interviewLimits } from '@/lib/authoring';

/**
 * 对谈章唯一的 AI 辅助模块。
 *
 * 一章只出现一个：作者给一句统一指令，模块把当前已暂存草稿里所有未回答的
 * 问题按每批五题顺序生成并接受，进度逐批可见。选题/回答的未保存修改不会
 * 进入生成（编辑态下模块锁定）。需要先审核正文时，正文通读与审核就在本
 * 模块内完成，不把作者支去定格章；首批生成时后端据此自动建立采访依据。
 */
export function InterviewInspirationPanel({
  playerId,
  draftId,
  draft,
  template,
  locked,
  onRunningChange,
}: {
  readonly playerId: string;
  readonly draftId: string;
  readonly draft: AuthoringDraft;
  readonly template: AuthoringTemplate;
  /** 编辑态锁定：必须先暂存，避免生成依据与本地未保存选题不一致。 */
  readonly locked: boolean;
  /** 编排开始/结束时通知父步骤，用于禁用会与生成冲突的编辑入口。 */
  readonly onRunningChange?: (running: boolean) => void;
}) {
  const limits = interviewLimits(template);
  const confirmDocuments = useConfirmDocuments(playerId, draftId);
  const runner = useInterviewAnswersRun(playerId, draftId);
  const [instruction, setInstruction] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);

  const workflow = draft.workflow;
  const storyReady = workflow.basic === 'accepted' && workflow.story === 'accepted';
  const basisActive = workflow.interview_basis !== null && workflow.interview_basis !== undefined;
  const documentsReady = workflow.documents_review === 'accepted';
  const needsDocumentReview = !basisActive && !documentsReady;
  const prerequisitesReady = storyReady && !needsDocumentReview;

  const unanswered = draft.content.interview
    .filter((item) => item.answer.trim() === '')
    .map((item) => item.question_id);

  useEffect(() => {
    onRunningChange?.(runner.running);
  }, [runner.running, onRunningChange]);

  const startRun = () => {
    const chunks: string[][] = [];
    for (let index = 0; index < unanswered.length; index += limits.batch) {
      chunks.push(unanswered.slice(index, index + limits.batch));
    }
    void runner.run(chunks, draft, instruction.trim());
  };

  const reviewBusy = confirmDocuments.isPending;

  return (
    <section>
      <header className="flex items-center gap-2">
        <SparkIcon />
        <h3 className="text-[13px] font-semibold text-accent">创作灵感 · 对谈回答</h3>
        <span className="text-[11px] text-content-faint">一个模块答完全章，接受前不改动你的材料</span>
      </header>
      <p className="mt-2 text-[12px] leading-relaxed text-content-muted">
        {template.operations.interview ?? ''} 一次最多处理 {limits.batch} 题，模块会自动分批顺序进行，
        已接受的回答直接写入题目列表。
      </p>

      {!storyReady ? (
        <p className="mt-3 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-[11px] text-warn">
          先在「来历」确认非空的过去故事，才能让灵感依据它代入对谈。
        </p>
      ) : null}

      {storyReady && needsDocumentReview ? (
        <div className="mt-3 rounded-lg border border-warn/40 bg-warn/10 p-3">
          <p className="text-[11px] leading-relaxed text-warn">
            第一批回答生成前，需要先通读并审核三份运行正文：它们是角色运行时真正读取的内容。
            选题后正文审核会重置，只需在这里再确认一次。
          </p>
          <details className="group mt-2">
            <summary className="cursor-pointer list-none text-[11px] font-medium text-warn marker:hidden">
              <span className="inline-flex items-center gap-1.5">
                <span className="transition-transform group-open:rotate-90">▸</span>
                通读三份正文
              </span>
            </summary>
            <div className="mt-2">
              <DocumentSheets
                form={draft.content}
                readOnly
                limits={{
                  profile: template.limits.profile ?? 0,
                  voice: template.limits.voice ?? 0,
                  relational_dynamics: template.limits.relational_dynamics ?? 0,
                }}
              />
            </div>
          </details>
          <label className="mt-2.5 flex items-start gap-2 text-[11px] leading-relaxed text-content-muted">
            <input
              type="checkbox"
              checked={acknowledged}
              disabled={reviewBusy}
              onChange={(event) => setAcknowledged(event.target.checked)}
              className="mt-0.5"
            />
            我已通读三份正文，确认与当前材料一致。
          </label>
          {confirmDocuments.isError ? (
            <p className="mt-1.5 text-[11px] text-danger">{errorMessage(confirmDocuments.error)}</p>
          ) : null}
          <button
            type="button"
            disabled={!acknowledged || reviewBusy}
            onClick={() => {
              void confirmDocuments
                .mutateAsync(draft.revision)
                .then(() => setAcknowledged(false))
                .catch(() => undefined);
            }}
            className="mt-2 rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] font-medium text-accent hover:bg-accent/20 disabled:opacity-40"
          >
            {reviewBusy ? '审核中…' : '审核通过'}
          </button>
        </div>
      ) : null}

      <div className="mt-3">
        <textarea
          value={instruction}
          maxLength={4000}
          rows={2}
          disabled={runner.running}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="可以留空，也可以统一交代 TA 回答时的语气、要保留或回避的内容…"
          className="w-full resize-none rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none transition-colors placeholder:text-content-faint focus:border-accent/60 disabled:opacity-60"
        />

        {runner.batches.length > 0 ? (
          <ul className="mt-3 grid gap-1.5">
            {runner.batches.map((batch) => (
              <li
                key={batch.index}
                className="flex items-center justify-between gap-2 rounded-lg bg-surface-sunken/60 px-3 py-2 text-[11px]"
              >
                <span className="text-content-muted">
                  第 {batch.index + 1} 批 · {batch.questionIds.length} 题
                </span>
                <BatchStatus batch={batch} active={runner.active} />
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-3">
          {runner.running ? (
            <>
              <span className="animate-breathe text-[12px] font-medium text-accent">
                {runner.active?.phase === 'accepting' ? '正在写入这批回答…' : '构思中…'}
                {runner.active !== null ? `（第 ${runner.active.index + 1} 批 · 第 ${runner.active.requests} 次请求）` : ''}
              </span>
              <button
                type="button"
                onClick={runner.stop}
                className="rounded-lg border border-border-strong px-3 py-1.5 text-[12px] text-content-muted hover:border-danger/60 hover:text-danger"
              >
                停止
              </button>
            </>
          ) : (
            <>
              {/* 编辑态优先：未保存选题不在草稿里，此时不能生成，只给暂存提示，
                  也不能按已保存草稿的空列表误报「都有回答了」。 */}
              {locked ? (
                <span className="text-[11px] text-warn">正在编辑选题或回答：先暂存本章，再请 TA 回答。</span>
              ) : unanswered.length === 0 ? (
                <span className="text-[12px] text-ok">保留的问题都有回答了，可以去确认本章。</span>
              ) : (
                <button
                  type="button"
                  disabled={!prerequisitesReady}
                  onClick={startRun}
                  className="rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
                >
                  为 {unanswered.length} 个未回答的问题请 TA 回答
                </button>
              )}
              {runner.batches.some((batch) => batch.status === 'failed') ? (
                <span className="text-[11px] text-danger">有批次未成功，修好后点上方按钮继续剩余问题。</span>
              ) : null}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function BatchStatus({
  batch,
  active,
}: {
  readonly batch: {
    readonly index: number;
    readonly status: string;
    readonly error?: string | undefined;
  };
  readonly active: { readonly index: number } | null;
}) {
  if (batch.status === 'accepted') return <span className="text-ok">✓ 已写入</span>;
  if (batch.status === 'failed') {
    return (
      <span className="text-danger" title={batch.error ?? ''}>
        未成功
      </span>
    );
  }
  if (active !== null && active.index === batch.index && batch.status === 'processing') {
    return <span className="text-accent">进行中…</span>;
  }
  return <span className="text-content-faint">等待中</span>;
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-3.5 text-accent" fill="currentColor" aria-hidden="true">
      <path d="M8 0l1.6 5.4L15 7l-5.4 1.6L8 14l-1.6-5.4L1 7l5.4-1.6L8 0z" />
    </svg>
  );
}
