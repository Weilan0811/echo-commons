import { useState } from 'react';
import { useConfirmStage } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { CandidatePanel } from '@/components/authoring/CandidatePanel';
import { DocumentSheets } from '@/components/authoring/DocumentSheets';
import { StageBadge, StepActionBar, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import { useDraftEditor } from '../useDraftEditor';
import type { StepProps } from './StepProps';

/**
 * 第一章：基础人设。
 *
 * 作者原稿（名字、描述、头像）与三份运行正文分列；确认前必须先保存，阶段
 * 确认针对的是服务端草稿。AI 起草完全可选，三份正文也可以全部手写。
 */
export function BasicStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmStage(playerId, draftId, 'basic');
  const [showHints, setShowHints] = useState(false);

  const limits = template.limits;
  const form = editor.form;
  const materialsReady =
    form.display_name.trim() !== ''
    && form.description.trim() !== ''
    && form.profile.trim() !== ''
    && form.voice.trim() !== ''
    && form.relational_dynamics.trim() !== '';
  const accepted = draft.workflow.basic === 'accepted';
  const canConfirm = !editor.dirty && materialsReady && !confirm.isPending;

  const onConfirm = () => {
    void confirm.mutateAsync(draft.revision).catch(() => {
      // 409 或阶段依赖错误在动作条上方呈现，作者重读状态后再操作。
    });
  };

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      <StepHeader
        index={0}
        title="初识"
        description="给 TA 一个名字和一两句话。三份正文是角色运行时真正读到的内容，现在可以手写，也可以先让灵感起草再改。"
      >
        <StageBadge status={draft.workflow.basic} />
      </StepHeader>

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        <ZoneHeading title="作者原稿" hint="你对这个人物的原始设定，与运行正文分开保存" />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium text-content-muted">名字</span>
            <input
              value={form.display_name}
              maxLength={limits.display_name}
              onChange={(event) => editor.patch({ display_name: event.target.value })}
              className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] outline-none focus:border-accent/60"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium text-content-muted">头像图片地址（可留空）</span>
            <input
              value={form.avatar_url ?? ''}
              maxLength={2000}
              onChange={(event) =>
                editor.patch({ avatar_url: event.target.value.trim() === '' ? null : event.target.value })
              }
              placeholder="留空则使用名字首字与专属配色"
              className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] outline-none placeholder:text-content-faint focus:border-accent/60"
            />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="text-[11px] font-medium text-content-muted">一两句话描述</span>
            <textarea
              value={form.description}
              maxLength={limits.description}
              rows={3}
              onChange={(event) => editor.patch({ description: event.target.value })}
              className="resize-none rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-accent/60"
            />
            <span className="tabular self-end text-[10px] text-content-faint">
              {form.description.length}/{limits.description}
            </span>
          </label>
        </div>

        <button
          type="button"
          onClick={() => setShowHints((value) => !value)}
          className="mt-2 text-[11px] text-accent/90 hover:underline"
        >
          {showHints ? '收起写作提示' : '没有头绪？看看可以想些什么'}
        </button>
        {showHints ? (
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {template.guidance.map((item) => (
              <li
                key={item.id}
                className="rounded-lg border border-dashed border-border-subtle bg-surface-sunken/50 px-3 py-2 text-[11px] leading-relaxed text-content-muted"
              >
                {item.question}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div>
        <ZoneHeading title="人物正文" hint="角色聊天时真正读到的三份文档；确认基础人设前请通读一遍" />
        <DocumentSheets
          form={form}
          limits={{
            profile: limits.profile ?? 0,
            voice: limits.voice ?? 0,
            relational_dynamics: limits.relational_dynamics ?? 0,
          }}
          onPatch={editor.patch}
        />
      </div>

      <CandidatePanel
        draft={draft}
        playerId={playerId}
        operation="basic"
        operationHint={template.operations.basic ?? ''}
        canGenerate={true}
      />

      {editor.conflict ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新（比如刚接受了一份建议），已重新载入最新内容，请在最新版本上继续修改。
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
          {editor.isSaving ? '保存中…' : '保存修改'}
        </button>
        {editor.dirty ? (
          <span className="text-[10px] text-content-faint">有未保存的修改，确认章节前请先保存</span>
        ) : null}

        <div className="ml-auto flex items-center gap-3">
          {accepted ? (
            <>
              <button
                type="button"
                onClick={() => onNavigate('final')}
                className="text-[12px] text-content-faint hover:text-content"
              >
                直接去定格
              </button>
              <button
                type="button"
                onClick={() => onNavigate('story')}
                className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110"
              >
                继续：来历 →
              </button>
            </>
          ) : (
            <>
              {!materialsReady ? (
                <span className="text-[10px] text-content-faint">名字、描述和三份正文都不能为空</span>
              ) : null}
              <button
                type="button"
                disabled={!canConfirm}
                onClick={onConfirm}
                className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
              >
                {confirm.isPending ? '确认中…' : '确认基础人设'}
              </button>
            </>
          )}
        </div>
      </StepActionBar>
    </div>
  );
}
