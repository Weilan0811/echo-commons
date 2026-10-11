import { useConfirmStage } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { CandidatePanel } from '@/components/authoring/CandidatePanel';
import { InspirationDrawer } from '@/components/authoring/InspirationDrawer';
import { DocumentSheets } from '@/components/authoring/DocumentSheets';
import { StageBadge, StepActionBar, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import { canConfirmStory, hasStory } from '@/lib/authoring';
import { useDraftEditor } from '../useDraftEditor';
import type { StepProps } from './StepProps';

/**
 * 第二章：过去故事。
 *
 * 故事是作者原稿，独立于三份运行正文保存；本章可以整体留白，留白后可直接
 * 去定格，但不能进入采访（采访要求已定稿且非空的故事）。章节默认核对态，
 * 「再次编辑」后才能改动，暂存后重新锁定；基础设定改动会让本章进入待复核。
 */
export function StoryStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmStage(playerId, draftId, 'story');
  const limits = template.limits;

  const workflow = draft.workflow;
  const status = workflow.story;
  const editing = editor.editing;
  const savedStoryReady = canConfirmStory(workflow, draft.content);
  const accepted = status === 'accepted';
  const storyPresent = hasStory(draft.content) || editor.form.story.trim() !== '';

  const onConfirm = () => {
    void confirm.mutateAsync(draft.revision).catch(() => undefined);
  };

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      <StepHeader
        index={1}
        title="来历"
        description="写下几个经历关键词或完整故事，也可以让灵感依据已定稿的人设构思。故事围绕少量重要经历即可，篇幅不设门槛，这一章也可以留白。"
      >
        <div className="flex items-center gap-2">
          <InspirationDrawer>
            <CandidatePanel
              draft={draft}
              playerId={playerId}
              operation="story"
              operationHint={template.operations.story ?? ''}
              canGenerate={!editing && workflow.basic === 'accepted'}
              generateHint={
                editing
                  ? '正在编辑本章：先暂存修改，再请 TA 起草。'
                  : '先回到「初识」确认基础人设，才能让灵感依据它构思故事。'
              }
            />
          </InspirationDrawer>
          <StageBadge status={status} />
        </div>
      </StepHeader>

      {status === 'review_required' ? (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-[11px] leading-relaxed text-warn">
          基础设定或正文有改动，故事需要重新过目。通读后确认故事仍然成立，即可重新定稿本章。
        </div>
      ) : null}

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        <ZoneHeading
          title="作者原稿 · 过去故事"
          hint={editing ? '编辑中：暂存后会重新锁定' : '这些经历会独立保存，并在校准后才影响运行正文'}
        />
        <textarea
          value={editor.form.story}
          maxLength={limits.story ?? 0}
          rows={14}
          disabled={!editing}
          onChange={(event) => editor.patch({ story: event.target.value })}
          placeholder="可以从一个关键事件写起：那时候 TA 在哪里，遇到了谁，做了什么决定…"
          className="w-full resize-y rounded-lg border border-border-subtle bg-surface-sunken px-3.5 py-3 text-[13px] leading-[1.9] outline-none transition-colors placeholder:text-content-faint focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-70"
        />
        <div className="tabular mt-1.5 text-right text-[10px] text-content-faint">
          {editor.form.story.length}/{limits.story ?? 0}
        </div>
      </div>

      <details className="group rounded-card border border-border-subtle bg-surface-overlay/30 p-4">
        <summary className="cursor-pointer list-none text-[12px] font-medium text-content-muted marker:hidden">
          <span className="inline-flex items-center gap-2">
            <span className="text-content-faint transition-transform group-open:rotate-90">▸</span>
            当前人物正文（只读）
          </span>
        </summary>
        <div className="mt-3">
          <DocumentSheets
            form={draft.content}
            readOnly
            limits={{
              profile: limits.profile ?? 0,
              voice: limits.voice ?? 0,
              relational_dynamics: limits.relational_dynamics ?? 0,
            }}
          />
        </div>
      </details>

      {editor.conflict ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新，已重新载入最新内容，请在最新版本上继续。
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
            <span className="ml-auto text-[10px] text-content-faint">暂存后回到核对，再确认本章或留白</span>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={editor.startEdit}
              className="rounded-lg border border-border-strong px-3.5 py-1.5 text-[12px] text-content-muted transition-colors hover:border-accent/60 hover:text-content"
            >
              再次编辑
            </button>

            <div className="ml-auto flex items-center gap-3">
              {accepted ? (
                <>
                  <button
                    type="button"
                    onClick={() => onNavigate('final')}
                    className="text-[12px] text-content-faint hover:text-content"
                  >
                    去定格
                  </button>
                  <button
                    type="button"
                    onClick={() => onNavigate('interview')}
                    className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110"
                  >
                    继续：对谈 →
                  </button>
                </>
              ) : storyPresent ? (
                <>
                  {!savedStoryReady ? (
                    <span className="text-[10px] text-content-faint">确认基础人设后才能定稿故事</span>
                  ) : null}
                  <button
                    type="button"
                    disabled={!savedStoryReady || confirm.isPending}
                    onClick={onConfirm}
                    className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
                  >
                    {confirm.isPending ? '确认中…' : '确认过去故事'}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => onNavigate('final')}
                  className="text-[12px] text-content-faint transition-colors hover:text-content"
                >
                  本章留白，直接去定格 →
                </button>
              )}
            </div>
          </>
        )}
      </StepActionBar>
    </div>
  );
}
