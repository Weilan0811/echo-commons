import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { AuthoringCandidate, AuthoringDraft } from '@/api/authoring';
import { request } from '@/api/http';
import { errorMessage } from '@/components/ErrorNotice';
import { queryKeys } from '@/api/queryKeys';
import { newUuid } from '@/lib/clientMessageId';
import { candidateHasConflicts, isCandidateStale } from '@/lib/authoring';

/** 处理中候选的轮询节奏，与接口层 useCandidate 保持一致。 */
const POLL_MS = 2_000;
/** 安全上限：正常候选约一分钟内完成，超期由后端在读取时标记失败。 */
const MAX_POLLS = 150;

export interface InterviewBatch {
  readonly index: number;
  readonly questionIds: readonly string[];
  readonly status: 'pending' | 'processing' | 'accepted' | 'failed';
  readonly error?: string | undefined;
}

export interface ActiveBatch {
  readonly index: number;
  readonly phase: 'thinking' | 'accepting';
  readonly requests: number;
}

/**
 * 采访回答的整章多批编排。
 *
 * 后端规定单次采访候选最多五题，因此「为全部未答题请 TA 回答」在这里拆成
 * 多批，顺序执行 生成 → 轮询 → 接受：每批接受后用返回的新修订号发下一批，
 * 并把权威草稿写回缓存，回答会逐批出现在题目列表里。失败只中断当前批，
 * 已接受的批次保留，之后可对剩余未答题再跑一次。
 */
export function useInterviewAnswersRun(playerId: string, draftId: string) {
  const client = useQueryClient();
  const [batches, setBatches] = useState<readonly InterviewBatch[]>([]);
  const [active, setActive] = useState<ActiveBatch | null>(null);
  const [running, setRunning] = useState(false);
  const stopRequested = useRef(false);

  useEffect(() => () => {
    stopRequested.current = true;
  }, []);

  const patchBatch = (index: number, patch: Partial<InterviewBatch>) => {
    setBatches((current) =>
      current.map((batch) => (batch.index === index ? { ...batch, ...patch } : batch)),
    );
  };

  const sleep = (ms: number) => new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

  const runOneBatch = async (
    batch: InterviewBatch,
    draft: AuthoringDraft,
    instruction: string,
  ): Promise<{ ok: boolean; draft: AuthoringDraft }> => {
    const candidateId = newUuid();
    let candidate: AuthoringCandidate;
    setActive({ index: batch.index, phase: 'thinking', requests: 1 });

    try {
      candidate = await request<AuthoringCandidate>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates`,
        {
          method: 'POST',
          body: {
            player_id: playerId,
            candidate_id: candidateId,
            expected_revision: draft.revision,
            instruction,
            operation: 'interview',
            question_ids: [...batch.questionIds],
          },
        },
      );
    } catch (error) {
      patchBatch(batch.index, { status: 'failed', error: describeError(error) });
      return { ok: false, draft };
    }

    let polls = 0;
    while (candidate.status === 'processing') {
      if (stopRequested.current || polls >= MAX_POLLS) {
        patchBatch(batch.index, {
          status: 'failed',
          error: stopRequested.current ? '已停止；本批未接受，不会改动草稿。' : '等待时间过长，已停止等待；可稍后对剩余题目重试。',
        });
        return { ok: false, draft };
      }
      await sleep(POLL_MS);
      if (stopRequested.current) {
        patchBatch(batch.index, { status: 'pending', error: undefined });
        return { ok: false, draft };
      }
      polls += 1;
      candidate = await request<AuthoringCandidate>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates/${encodeURIComponent(candidateId)}`,
        { query: { player_id: playerId } },
      );
      setActive({ index: batch.index, phase: 'thinking', requests: candidate.model_requests });
    }

    if (candidate.status === 'failed') {
      patchBatch(batch.index, {
        status: 'failed',
        error: '这批回答未生成成功，可以重新尝试。',
      });
      return { ok: false, draft };
    }

    if (isCandidateStale(candidate, draft) || candidateHasConflicts(candidate)) {
      patchBatch(batch.index, {
        status: 'failed',
        error: '这批建议与当前草稿不一致，请对剩余题目重新生成。',
      });
      return { ok: false, draft };
    }

    try {
      setActive({ index: batch.index, phase: 'accepting', requests: candidate.model_requests });
      const updated = await request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates/${encodeURIComponent(candidateId)}/accept`,
        {
          method: 'POST',
          body: { player_id: playerId, expected_revision: draft.revision },
        },
      );
      client.setQueryData(queryKeys.authoring.draft(playerId, draftId), updated);
      patchBatch(batch.index, { status: 'accepted', error: undefined });
      return { ok: true, draft: updated };
    } catch (error) {
      patchBatch(batch.index, { status: 'failed', error: describeError(error) });
      return { ok: false, draft };
    }
  };

  /** 对给定题目批次从头顺序执行；调用方保证批次来自当前已暂存草稿。 */
  const run = async (
    chunks: readonly (readonly string[])[],
    startDraft: AuthoringDraft,
    instruction: string,
  ) => {
    stopRequested.current = false;
    setBatches(chunks.map((questionIds, index) => ({ index, questionIds, status: 'pending' })));
    setRunning(true);

    let current = startDraft;
    for (let index = 0; index < chunks.length; index += 1) {
      if (stopRequested.current) break;
      patchBatch(index, { status: 'processing', error: undefined });
      const result = await runOneBatch(
        { index, questionIds: chunks[index]!, status: 'processing' },
        current,
        instruction,
      );
      current = result.draft;
      if (!result.ok) break;
    }

    setActive(null);
    setRunning(false);
  };

  const stop = () => {
    stopRequested.current = true;
  };

  return { batches, active, running, run, stop };
}

function describeError(error: unknown): string {
  return errorMessage(error);
}
