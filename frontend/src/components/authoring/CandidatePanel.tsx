import { useEffect, useMemo, useState } from 'react';
import {
  useAcceptCandidate,
  useCandidate,
  useGenerateCandidate,
  type AuthoringCandidate,
  type AuthoringDraft,
  type AuthoringOperation,
} from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { newUuid } from '@/lib/clientMessageId';
import {
  OPERATION_SCOPE,
  candidateClock,
  candidateHasConflicts,
  isCandidateStale,
} from '@/lib/authoring';
import { CandidateOutputView } from './candidateViews';

/**
 * 「创作灵感」面板：四类 AI 操作共用同一套生命周期。
 *
 * 候选编号在一次生成意图产生时确定，失败后重来使用新编号；处理中按固定节奏
 * 轮询，本地倒计时归零只表示「正在确认状态」，不提前宣布失败。
 */
export function CandidatePanel({
  draft,
  playerId,
  operation,
  operationHint,
  canGenerate,
  generateHint,
  questionIds,
}: {
  readonly draft: AuthoringDraft;
  readonly playerId: string;
  readonly operation: AuthoringOperation;
  readonly operationHint: string;
  readonly canGenerate: boolean;
  readonly generateHint?: string;
  /** 仅采访操作：本批一至五个题目编号；变化时应由父组件换 key 重置面板。 */
  readonly questionIds?: readonly string[];
}) {
  const [instruction, setInstruction] = useState('');
  const [candidateId, setCandidateId] = useState<string | null>(null);
  const generate = useGenerateCandidate(playerId, draft.draft_id);
  const candidateQuery = useCandidate(playerId, draft.draft_id, candidateId);
  const accept = useAcceptCandidate(playerId, draft.draft_id, candidateId ?? '');
  const [now, setNow] = useState(() => Date.now());

  const candidate = candidateQuery.data ?? null;
  const processing = candidate?.status === 'processing';

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [processing]);

  const stale = candidate !== null && isCandidateStale(candidate, draft);
  const hasConflicts = candidate !== null && candidateHasConflicts(candidate);
  const acceptDisabled = stale || hasConflicts || accept.isPending;

  const startGeneration = () => {
    const id = newUuid();
    setCandidateId(id);
    void generate
      .mutateAsync({
        candidateId: id,
        expectedRevision: draft.revision,
        operation,
        instruction: instruction.trim(),
        questionIds,
      })
      .catch(() => {
        // 编号已占用或请求被拒时保留面板，错误在下方呈现，可用新编号重来。
      });
  };

  return (
    <section className="rounded-card border border-accent/25 bg-accent-soft/40 p-4">
      <header className="flex items-center gap-2">
        <SparkIcon />
        <h3 className="text-[13px] font-semibold text-accent">创作灵感</h3>
        <span className="text-[11px] text-content-faint">AI 只提建议，接受前不改动你的材料</span>
      </header>
      <p className="mt-2 text-[12px] leading-relaxed text-content-muted">{operationHint}</p>

      {candidateId === null ? (
        <div className="mt-3 flex flex-col gap-2.5">
          <textarea
            value={instruction}
            maxLength={4000}
            onChange={(event) => setInstruction(event.target.value)}
            rows={2}
            placeholder="可以留空，也可以告诉它特别想保留或补充什么…"
            className="resize-none rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
          />
          {canGenerate ? null : (
            <p className="text-[11px] text-warn">{generateHint ?? '当前还不能生成，先完成前置步骤。'}</p>
          )}
          <div>
            <button
              type="button"
              disabled={!canGenerate || generate.isPending}
              onClick={startGeneration}
              className="rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
            >
              {generate.isPending ? '正在请求…' : '请 TA 起草'}
            </button>
          </div>
          {generate.isError ? <ErrorNotice error={generate.error} /> : null}
        </div>
      ) : (
        <div className="mt-3">
          <CandidateBody
            candidate={candidate}
            isLoading={candidateQuery.isPending}
            now={now}
            draftRevision={draft.revision}
            stale={stale}
            hasConflicts={hasConflicts}
            acceptDisabled={acceptDisabled}
            accepting={accept.isPending}
            onAccept={() => {
              void accept.mutateAsync(draft.revision).then(() => {
                setCandidateId(null);
              }).catch(() => {
                // 409 等冲突保留候选与材料，错误在下方呈现并由草稿重读解决。
              });
            }}
            onRegenerate={startGeneration}
            acceptError={accept.error}
            queryError={candidateQuery.error}
          />
        </div>
      )}
    </section>
  );
}

function CandidateBody({
  candidate,
  isLoading,
  now,
  draftRevision,
  stale,
  hasConflicts,
  acceptDisabled,
  accepting,
  onAccept,
  onRegenerate,
  acceptError,
  queryError,
}: {
  readonly candidate: AuthoringCandidate | null;
  readonly isLoading: boolean;
  readonly now: number;
  readonly draftRevision: number;
  readonly stale: boolean;
  readonly hasConflicts: boolean;
  readonly acceptDisabled: boolean;
  readonly accepting: boolean;
  readonly onAccept: () => void;
  readonly onRegenerate: () => void;
  readonly acceptError: unknown;
  readonly queryError: unknown;
}) {
  const clock = useMemo(
    () => (candidate === null ? null : candidateClock(candidate, now)),
    [candidate, now],
  );

  if (isLoading && candidate === null) {
    return <p className="animate-breathe py-4 text-[12px] text-content-faint">构思中…</p>;
  }
  if (queryError !== null && candidate === null) {
    return (
      <div className="flex flex-col gap-2">
        <ErrorNotice error={queryError} />
        <button type="button" onClick={onRegenerate} className="self-start text-[12px] text-accent hover:underline">
          换个灵感重来
        </button>
      </div>
    );
  }
  if (candidate === null) return null;

  if (candidate.status === 'processing') {
    return (
      <div className="flex flex-col gap-2 rounded-lg bg-surface-sunken/50 p-3.5">
        <p className="animate-breathe text-[13px] font-medium text-accent">
          {clock?.state === 'confirming' ? '正在确认状态…' : '构思中…'}
        </p>
        <p className="tabular text-[11px] text-content-faint">
          第 {candidate.model_requests} 次模型请求
          {clock?.state === 'running' ? ` · 剩余约 ${formatRemaining(clock.remainingMs)}` : ''}
        </p>
        {clock?.state === 'confirming' ? (
          <p className="text-[10px] leading-relaxed text-content-faint">
            期限已到，后端正在读取时确认结果，请稍候——这不等于失败。
          </p>
        ) : null}
      </div>
    );
  }

  if (candidate.status === 'failed') {
    return (
      <div className="flex flex-col gap-2">
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-3">
          <p className="text-[13px] text-danger">这次生成没成功，可以重来。</p>
          {candidate.error_code !== null ? (
            <p className="tabular mt-1 text-[10px] text-content-faint">原因编号：{candidate.error_code}</p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onRegenerate}
          className="self-start rounded-lg border border-accent/50 bg-accent-soft px-3 py-1.5 text-[12px] text-accent hover:bg-accent/20"
        >
          换个灵感重来
        </button>
      </div>
    );
  }

  return (
    <div className="animate-rise-in flex flex-col gap-3">
      <CandidateOutputView candidate={candidate} />
      {stale ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          这份建议依据的是 r{candidate.input_revision} 版草稿，当前已是 r{draftRevision} 版。
          内容仍可阅读，但不能直接接受，请重新生成。
        </p>
      ) : null}
      {hasConflicts ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 p-2.5 text-[11px] text-danger">
          校准里有需要你决定的冲突，无法整体接受；可以改材料后重新校准，或手工编辑正文。
        </p>
      ) : null}
      {acceptError !== null ? (
        <p className="text-[11px] text-danger">{errorMessage(acceptError)}</p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={acceptDisabled}
          onClick={onAccept}
          className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
        >
          {accepting ? '接受中…' : OPERATION_SCOPE[candidate.operation]}
        </button>
        <button
          type="button"
          onClick={onRegenerate}
          className="text-[12px] text-content-faint transition-colors hover:text-content-muted"
        >
          不满意，重新生成
        </button>
      </div>
    </div>
  );
}

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-3.5 text-accent" fill="currentColor" aria-hidden="true">
      <path d="M8 0l1.6 5.4L15 7l-5.4 1.6L8 14l-1.6-5.4L1 7l5.4-1.6L8 0z" />
    </svg>
  );
}
