import { useState } from 'react';
import { useConfirmDocuments } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { DocumentSheets } from '@/components/authoring/DocumentSheets';
import { ZoneHeading } from '@/components/authoring/StepChrome';
import { hasStory } from '@/lib/authoring';
import { useDraftEditor } from '../useDraftEditor';
import type { StepProps } from './StepProps';

/**
 * 三份运行正文的审核卡。
 *
 * 审核声明的是「正文与当前材料一致」，因此允许先手工改正文、保存后再勾选。
 * 故事存在时必须先确认故事才能审核（与服务端门控一致）；采访章的缺口由
 * 终章清单另外表达，不在这里重复拦截。
 */
export function DocumentsReviewCard({
  playerId,
  draftId,
  draft,
  template,
}: Pick<StepProps, 'playerId' | 'draftId' | 'draft' | 'template'>) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmDocuments(playerId, draftId);
  const [editing, setEditing] = useState(false);
  const [checked, setChecked] = useState(false);

  const limits = template.limits;
  const accepted = draft.workflow.documents_review === 'accepted';
  const storySatisfied = !hasStory(draft.content) || draft.workflow.story === 'accepted';
  const canReview =
    draft.workflow.basic === 'accepted'
    && storySatisfied
    && !editor.dirty
    && checked
    && !confirm.isPending;

  const docLimits = {
    profile: limits.profile ?? 0,
    voice: limits.voice ?? 0,
    relational_dynamics: limits.relational_dynamics ?? 0,
  };

  return (
    <div className="rounded-card border border-border-subtle bg-surface p-4">
      <ZoneHeading
        title="审核三份运行正文"
        hint="角色运行时只读这三份文档；故事与采访是独立保存的作者材料"
      />

      {accepted ? (
        <p className="mb-3 rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[11px] text-ok">
          三份正文已审核，与当前材料一致。后续材料变化会让这里重新进入待审核。
        </p>
      ) : (
        <p className="mb-3 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] leading-relaxed text-warn">
          通读三份正文，确认它们与你已确认的材料一致。没有来源支持的经历与能力不应出现在正文里。
        </p>
      )}

      {editing ? (
        <DocumentSheets form={editor.form} limits={docLimits} onPatch={editor.patch} />
      ) : (
        <DocumentSheets form={draft.content} limits={docLimits} readOnly />
      )}

      {editor.conflict ? (
        <p className="mt-3 rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新，已重新载入最新内容。
        </p>
      ) : null}
      {editor.saveError !== null ? (
        <div className="mt-3"><ErrorNotice error={editor.saveError} /></div>
      ) : null}
      {confirm.isError ? <p className="mt-3 text-[11px] text-danger">{errorMessage(confirm.error)}</p> : null}

      <div className="mt-4">
        {editing ? (
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={!editor.dirty || editor.isSaving}
              onClick={() => {
                void editor.save().then((ok) => {
                  if (ok) setEditing(false);
                });
              }}
              className="rounded-lg bg-accent px-3.5 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110 disabled:opacity-40"
            >
              {editor.isSaving ? '保存中…' : '保存正文'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="text-[12px] text-content-faint hover:text-content"
            >
              放弃修改
            </button>
          </div>
        ) : accepted ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[12px] text-content-faint underline-offset-2 hover:text-content hover:underline"
          >
            需要手工改正文
          </button>
        ) : (
          <div className="flex flex-col gap-3">
            <label className="flex items-start gap-2 text-[12px] text-content-muted">
              <input
                type="checkbox"
                checked={checked}
                disabled={editor.dirty}
                onChange={(event) => setChecked(event.target.checked)}
                className="mt-0.5 accent-amber-500"
              />
              <span>我已通读三份正文，确认它们与当前的人设、故事和采访一致。</span>
            </label>
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={!canReview}
                onClick={() => {
                  void confirm.mutateAsync(draft.revision).then(() => setChecked(false)).catch(() => undefined);
                }}
                className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
              >
                {confirm.isPending ? '提交中…' : '审核通过'}
              </button>
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="text-[12px] text-content-faint underline-offset-2 hover:text-content hover:underline"
              >
                先手工改正文
              </button>
              {!storySatisfied ? (
                <span className="text-[10px] text-warn">有故事时先到「来历」确认故事</span>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
