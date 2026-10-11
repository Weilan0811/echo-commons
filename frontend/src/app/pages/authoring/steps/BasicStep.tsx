import { useState } from 'react';
import { useConfirmStage, useTemplateDocuments } from '@/api/authoring';
import { ErrorNotice, errorMessage } from '@/components/ErrorNotice';
import { CandidatePanel } from '@/components/authoring/CandidatePanel';
import { InspirationDrawer } from '@/components/authoring/InspirationDrawer';
import { DocumentSheets } from '@/components/authoring/DocumentSheets';
import { StageBadge, StepActionBar, StepHeader, ZoneHeading } from '@/components/authoring/StepChrome';
import { IntroductionCard } from '@/components/authoring/IntroductionCard';
import { useDraftEditor } from '../useDraftEditor';
import { IllustrationPicker } from '@/components/IllustrationPicker';
import { apiBaseUrl } from '@/api/http';
import type { StepProps } from './StepProps';

/**
 * 第一章：基础人设。
 *
 * 作者原稿（名字、描述、头像）与三份运行正文分列。章节默认核对态：内容锁定
 * 只读，「再次编辑」进入编辑态，暂存后重新锁定；章节确认与 AI 起草只面向
 * 已暂存内容。
 */
export function BasicStep({ playerId, draftId, draft, template, onNavigate }: StepProps) {
  const editor = useDraftEditor(playerId, draft);
  const confirm = useConfirmStage(playerId, draftId, 'basic');
  const preview = useTemplateDocuments(playerId, draftId);
  const acceptTemplate = useTemplateDocuments(playerId, draftId, true);
  const [illustrationRevision, setIllustrationRevision] = useState(draft.revision);
  const [showHints, setShowHints] = useState(false);
  const [showIllustrations, setShowIllustrations] = useState(false);

  const limits = template.limits;
  const form = editor.form;
  const editing = editor.editing;
  const materialsReady =
    form.display_name.trim() !== ''
    && form.description.trim() !== ''
    && form.profile.trim() !== ''
    && form.voice.trim() !== ''
    && form.relational_dynamics.trim() !== '';
  const accepted = draft.workflow.basic === 'accepted';
  const templatePreview = preview.data && 'output' in preview.data ? preview.data : null;
  const canConfirm = !editing && materialsReady && !confirm.isPending;

  const onConfirm = () => {
    void confirm.mutateAsync(draft.revision).catch(() => {
      // 409 或阶段依赖错误在动作条上方呈现，作者重读状态后再操作。
    });
  };

  return (
    <div className="flex animate-rise-in flex-col gap-5 pb-2">
      {showIllustrations ? <IllustrationPicker playerId={playerId} draft={{ id: draftId, revision: illustrationRevision }}
        onClose={() => setShowIllustrations(false)}
        onSelect={(asset) => editor.save({ ...form, avatar_url: null, avatar_asset_id: asset.asset_id })} /> : null}
      <StepHeader
        index={0}
        title="初识"
        description="像写一张自介卡，记下 TA 的生活和模样。详细设定可以按资料生成，也可以手写或请灵感助手帮忙。"
      >
        <div className="flex items-center gap-2">
          <InspirationDrawer>
            <CandidatePanel
              draft={draft}
              playerId={playerId}
              operation="basic"
              operationHint={template.operations.basic ?? ''}
              canGenerate={!editing}
              generateHint="正在编辑本章：先暂存修改，再请 TA 起草。"
            />
          </InspirationDrawer>
          <StageBadge status={draft.workflow.basic} />
        </div>
      </StepHeader>

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        <ZoneHeading
          title="自介卡"
          hint={editing ? '编辑中：暂存后会重新锁定' : '已锁定，点下方「再次编辑」修改'}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium text-content-muted">名字</span>
            <input
              value={form.display_name}
              maxLength={limits.display_name}
              disabled={!editing}
              onChange={(event) => editor.patch({ display_name: event.target.value })}
              className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] outline-none focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-70"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium text-content-muted">头像图片地址（可留空）</span>
            <input
              value={form.avatar_url ?? ''}
              maxLength={2000}
              disabled={!editing}
              onChange={(event) =>
                editor.patch({ avatar_url: event.target.value.trim() === '' ? null : event.target.value, avatar_asset_id: null })
              }
              placeholder="留空则使用名字首字与专属配色"
              className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] outline-none placeholder:text-content-faint focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-70"
            />
          </label>
          <label className="flex flex-col gap-1.5 sm:col-span-2">
            <span className="text-[11px] font-medium text-content-muted">一两句话描述</span>
            <textarea
              value={form.description}
              maxLength={limits.description}
              rows={3}
              disabled={!editing}
              onChange={(event) => editor.patch({ description: event.target.value })}
              className="resize-none rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-accent/60 disabled:cursor-not-allowed disabled:opacity-70"
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

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_180px]">
        <IntroductionCard introduction={form.introduction ?? {}} readOnly={!editing}
          onChange={(introduction) => editor.patch({ introduction })}
          busy={editor.isSaving}
          onIllustrate={() => {
            void (async () => {
              const saved = await editor.save();
              if (!saved) return;
              // 保存后的版本从权威缓存读取，避免 React 重绘前使用旧修订号。
              const latest = editor.savedDraft.current;
              if (latest) { setIllustrationRevision(latest.revision); setShowIllustrations(true); }
            })();
          }} />
        <aside className="paper-sheet rounded-xl border border-border-subtle p-3 lg:sticky lg:top-5">
          {form.avatar_asset_id || form.avatar_url ? <img
            src={form.avatar_asset_id ? `${apiBaseUrl()}/api/assets/${form.avatar_asset_id}/images/standard` : form.avatar_url!}
            alt="角色形象预览" className="aspect-[3/4] w-full rounded-lg object-cover" />
            : <div className="flex aspect-[3/4] items-center justify-center rounded-lg bg-accent/10 text-4xl text-accent">{form.display_name.slice(0, 1)}</div>}
          <p className="mt-3 text-center text-sm font-medium">{form.display_name}</p>
          <p className="mt-1 text-center text-xs text-content-faint">形象可选，外貌资料在左侧填写</p>
        </aside>
      </div>

      <details className="rounded-xl border border-border-subtle bg-surface p-4">
        <summary className="cursor-pointer text-sm font-semibold">详细设定</summary>
        <div className="mt-4">
          <ZoneHeading title="人物正文" hint="按资料生成会先展示差异；接受后才替换描述和三份正文" />
          <button type="button" disabled={editing || preview.isPending} onClick={() => preview.mutate(draft.revision)}
            className="mb-4 rounded-lg border border-border-strong px-3 py-2 text-xs disabled:opacity-40">按资料生成正文</button>
          {templatePreview ? <section aria-label="模板正文差异" className="mb-4 rounded-lg border border-accent/30 p-3">
            <p className="mb-3 text-xs text-content-muted">原稿完整保留；核对后接受，或继续编辑原稿。</p>
            {(['description', 'profile', 'voice', 'relational_dynamics'] as const).map((field) => <details key={field} className="mb-2">
              <summary className="cursor-pointer text-xs">{{ description: '人物简述', profile: '人物档案', voice: '说话习惯', relational_dynamics: '关系倾向' }[field]}{form[field] === templatePreview.output[field] ? ' · 内容相同' : ' · 内容有变化'}</summary>
              <div className="mt-2 grid gap-3 sm:grid-cols-2"><div><p className="text-xs text-content-faint">原稿</p><p className="whitespace-pre-wrap text-xs leading-relaxed">{form[field]}</p></div><div><p className="text-xs text-accent">按资料生成</p><p className="whitespace-pre-wrap text-xs leading-relaxed">{templatePreview.output[field]}</p></div></div>
            </details>)}
            <button type="button" disabled={editing || acceptTemplate.isPending || templatePreview.input_revision !== draft.revision}
              onClick={() => acceptTemplate.mutate(templatePreview.input_revision, { onSuccess: () => preview.reset() })}
              className="mt-2 rounded-lg bg-accent px-3 py-2 text-xs text-accent-ink disabled:opacity-40">接受模板正文</button>
            <button type="button" onClick={() => preview.reset()} className="ml-3 text-xs text-content-muted">保留原稿</button>
          </section> : null}
          {preview.error ? <ErrorNotice error={preview.error} /> : null}
          {acceptTemplate.error ? <ErrorNotice error={acceptTemplate.error} /> : null}
          <DocumentSheets form={form} limits={{ profile: limits.profile ?? 0, voice: limits.voice ?? 0, relational_dynamics: limits.relational_dynamics ?? 0 }} readOnly={!editing} onPatch={editor.patch} />
        </div>
      </details>

      {editor.conflict ? (
        <p className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-[11px] text-warn">
          草稿已被其他操作更新（比如刚接受了一份建议），已重新载入最新内容，请在最新版本上继续修改。
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
            <span className="ml-auto text-[10px] text-content-faint">暂存后回到核对，再确认本章</span>
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
          </>
        )}
      </StepActionBar>
    </div>
  );
}
