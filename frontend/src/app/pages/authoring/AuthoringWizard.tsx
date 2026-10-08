import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useDraft, useAuthoringTemplate } from '@/api/authoring';
import { ErrorNotice } from '@/components/ErrorNotice';
import { PersonaCard } from '@/components/authoring/PersonaCard';
import { ChapterRail } from '@/components/authoring/ChapterRail';
import { documentsReviewText, type AuthoringChapter } from '@/lib/authoring';
import type { AuthoringWorkflow } from '@/api/authoring';
import type { StepProps } from './steps/StepProps';
import { BasicStep } from './steps/BasicStep';
import { StoryStep } from './steps/StoryStep';
import { InterviewStep } from './steps/InterviewStep';
import { ConfirmStep } from './steps/ConfirmStep';

/**
 * 四章创作向导。
 *
 * 左侧是贯穿全程的人物卡与章节轨，右侧是当前章节；顶部始终有一行三份正文的
 * 审核状态，避免作者在前三章看不到正文待审核。章节不锁死，允许来回修改，
 * 下游复核由各章与状态条表达。
 */
export function AuthoringWizard({
  playerId,
  draftId,
}: {
  readonly playerId: string;
  readonly draftId: string;
}) {
  const draftQuery = useDraft(playerId, draftId);
  const templateQuery = useAuthoringTemplate();
  const [chapter, setChapter] = useState<AuthoringChapter>('basic');

  if (draftQuery.isPending || templateQuery.isPending) {
    return (
      <WizardShell strip={null} sidebar={null}>
        <p className="px-8 py-10 text-[12px] text-content-faint">正在翻开人物志…</p>
      </WizardShell>
    );
  }

  if (draftQuery.isError) {
    return (
      <WizardShell strip={null} sidebar={null}>
        <div className="px-8 py-10">
          <ErrorNotice error={draftQuery.error} onRetry={() => void draftQuery.refetch()} />
          <p className="mt-4 text-[12px]">
            <Link to="/app/characters" className="text-accent hover:underline">
              回到角色页
            </Link>
          </p>
        </div>
      </WizardShell>
    );
  }

  if (templateQuery.isError) {
    return (
      <WizardShell strip={null} sidebar={null}>
        <div className="px-8 py-10">
          <ErrorNotice error={templateQuery.error} onRetry={() => void templateQuery.refetch()} />
        </div>
      </WizardShell>
    );
  }

  const draft = draftQuery.data;
  const template = templateQuery.data;
  // 固定后的草稿只读，统一留在终章，章节轨只用于回看状态。
  const locked = draft.status === 'confirmed' || draft.confirmed_blueprint_id !== null;
  const activeChapter = locked ? 'final' : chapter;
  const step: StepProps = {
    playerId,
    draftId,
    draft,
    template,
    onNavigate: (next) => {
      if (!locked) setChapter(next);
    },
  };

  const sidebar = (
    <div className="flex flex-col gap-5">
      <PersonaCard draft={draft} />
      <ChapterRail
        workflow={draft.workflow}
        content={draft.content}
        active={activeChapter}
        locked={locked}
        onSelect={(next) => {
          if (!locked) setChapter(next);
        }}
      />
    </div>
  );

  return (
    <WizardShell strip={<DocumentsReviewStrip workflow={draft.workflow} />} sidebar={sidebar}>
      {activeChapter === 'basic' ? <BasicStep {...step} /> : null}
      {activeChapter === 'story' ? <StoryStep {...step} /> : null}
      {activeChapter === 'interview' ? <InterviewStep {...step} /> : null}
      {activeChapter === 'final' ? <ConfirmStep {...step} /> : null}
    </WizardShell>
  );
}

/** 顶部跨阶段状态条：三份正文的审核状态不属于任何单章，因此每步都可见。 */
function DocumentsReviewStrip({ workflow }: { readonly workflow: AuthoringWorkflow }) {
  const accepted = workflow.documents_review === 'accepted';
  return (
    <div
      className={`flex shrink-0 items-center gap-2 rounded-lg border px-3.5 py-2 text-[11px] ${
        accepted ? 'border-ok/30 bg-ok/10 text-ok' : 'border-warn/30 bg-warn/10 text-warn'
      }`}
    >
      <span className={`inline-block size-1.5 rounded-full ${accepted ? 'bg-ok' : 'bg-warn animate-breathe'}`} />
      {documentsReviewText(workflow)}
    </div>
  );
}

/**
 * 向导两栏布局。加载与错误态没有侧栏数据，允许传 null；侧栏存在时固定宽度，
 * 章节内容占剩余并独立滚动。
 */
function WizardShell({
  strip,
  sidebar,
  children,
}: {
  readonly strip: ReactNode;
  readonly sidebar: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <div className="mx-auto flex h-full max-w-6xl gap-6 px-6 py-6">
      {sidebar === null ? null : (
        <aside className="w-64 shrink-0 overflow-y-auto pb-4">{sidebar}</aside>
      )}
      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto pb-6 pr-1">
        {strip}
        {children}
      </section>
    </div>
  );
}
