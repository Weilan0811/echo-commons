import { useNavigate } from 'react-router';
import { useCopyDraft } from '@/api/authoring';
import { CandidatePanel } from '@/components/authoring/CandidatePanel';
import { InspirationDrawer } from '@/components/authoring/InspirationDrawer';
import { StageBadge, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import {
  canCalibrate,
  canFinalize,
  finalizeBlockers,
  hasStory,
  interviewLimits,
} from '@/lib/authoring';
import { DocumentsReviewCard } from './DocumentsReviewCard';
import { FinalizePanel } from './FinalizePanel';
import { InstancePanel } from './InstancePanel';
import type { StepProps } from './StepProps';

/**
 * 终章：校准、审核、定格与入住。
 *
 * 校准候选处理的是三份正文而不是某一章的材料，因此放在三章材料齐备的这里；
 * 定格成功后草稿只读，界面只提供「复制为新草稿」与建实例两个后续动作。
 */
export function ConfirmStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const navigate = useNavigate();
  const copy = useCopyDraft(playerId, draftId);
  const limits = interviewLimits(template);
  const workflow = draft.workflow;
  const finalized = draft.status === 'confirmed' || draft.confirmed_blueprint_id !== null;
  const blockers = finalizeBlockers(workflow, draft.content, limits);
  const hasMaterials = hasStory(draft.content) || draft.content.interview.length > 0;

  if (finalized && draft.confirmed_blueprint_id !== null) {
    return (
      <div className="flex animate-rise-in flex-col gap-5 pb-2">
        <StepHeader index={3} title="定格" description="人物已经固定，内容不再随草稿变化。">
          <StageBadge status="accepted" />
        </StepHeader>

        <div className="rounded-card border border-ok/30 bg-ok/10 p-5">
          <p className="text-[14px] font-semibold text-ok">人物已定格</p>
          <p className="mt-1.5 text-[12px] text-content-muted">
            {draft.content.display_name} 已成为固定人物资源。
          </p>
          <p className="tabular mt-1 break-all text-[10px] text-content-faint">
            {draft.confirmed_blueprint_id} · 内容版本 0.1.0
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={copy.isPending}
              onClick={() => {
                void copy
                  .mutateAsync()
                  .then((newDraft) => navigate(`/app/characters/authoring/${newDraft.draft_id}`))
                  .catch(() => undefined);
              }}
              className="rounded-lg border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] text-accent hover:bg-accent/20 disabled:opacity-40"
            >
              {copy.isPending ? '复制中…' : '复制为新草稿继续修改'}
            </button>
            <button
              type="button"
              onClick={() => onNavigate('basic')}
              className="text-[12px] text-content-faint hover:text-content"
            >
              回看材料
            </button>
          </div>
          {copy.isError ? (
            <p className="mt-2 text-[11px] text-danger">复制失败，请稍后重试。</p>
          ) : null}
        </div>

        <InstancePanel
          playerId={playerId}
          blueprintId={draft.confirmed_blueprint_id}
          displayName={draft.content.display_name}
          personId={draft.content.person_id ?? null}
          avatarUrl={draft.content.avatar_url ?? null}
          hasMaterials={hasMaterials}
          materialNotice={template.material_notice}
        />
      </div>
    );
  }

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      <StepHeader
        index={3}
        title="定格"
        description="通读并审核三份运行正文，必要时用一次校准把故事与采访里的关键信息提炼进正文，然后固定人物。"
      >
        <div className="flex items-center gap-2">
          <InspirationDrawer label="灵感校准">
            <CandidatePanel
              draft={draft}
              playerId={playerId}
              operation="calibrate"
              operationHint={template.operations.calibrate ?? ''}
              canGenerate={canCalibrate(workflow, draft.content)}
              generateHint="先确认已经填写的章节，才能一次性校准三份正文。"
            />
          </InspirationDrawer>
          <StageBadge status={canFinalize(workflow, draft.content) ? 'accepted' : 'review_required'} />
        </div>
      </StepHeader>

      <CompletionChecklist draft={draft} />

      <DocumentsReviewCard playerId={playerId} draftId={draftId} draft={draft} template={template} />

      <FinalizePanel
        playerId={playerId}
        draft={draft}
        fixedNotice={template.fixed_background_notice}
        canFinalize={canFinalize(workflow, draft.content)}
        blockers={blockers}
        onConfirmed={() => undefined}
      />
    </div>
  );
}

/** 定稿清单：直接呈现各章与正文的状态，留白是合法终态。 */
function CompletionChecklist({ draft }: { readonly draft: StepProps['draft'] }) {
  const content = draft.content;
  const rows = [
    { label: '确认基础人设', state: draft.workflow.basic === 'accepted' },
    {
      label: '过去故事',
      state:
        draft.workflow.story === 'accepted'
          ? 'done'
          : hasStory(content)
            ? 'todo'
            : 'skip',
    },
    {
      label: '人物采访',
      state:
        draft.workflow.interview === 'accepted'
          ? 'done'
          : content.interview.length > 0
            ? 'todo'
            : 'skip',
    },
    { label: '审核三份运行正文', state: draft.workflow.documents_review === 'accepted' },
  ] as const;

  return (
    <div className="rounded-card border border-border-subtle bg-surface p-4">
      <ZoneHeading title="定格清单" hint="留白的章节不需要确认；已填写的章节不能有待复核" />
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {rows.map((row) => {
          const state = typeof row.state === 'boolean' ? (row.state ? 'done' : 'todo') : row.state;
          return (
            <li key={row.label} className="flex items-center gap-2 text-[12px]">
              <span
                className={
                  state === 'done' ? 'text-ok' : state === 'skip' ? 'text-content-faint' : 'text-warn'
                }
              >
                {state === 'done' ? '✓' : state === 'skip' ? '–' : '○'}
              </span>
              <span className={state === 'todo' ? 'text-content-muted' : 'text-content-faint'}>
                {row.label}
                {state === 'skip' ? '（留白）' : ''}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
