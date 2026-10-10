import { useState } from 'react';
import { useNavigate } from 'react-router';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCreateDraft, useAuthoringTemplate } from '@/api/authoring';

/**
 * 人物志第一页：只需名字和一句话即可开始。
 *
 * 草稿创建成功后用 replace 进入正式向导，避免返回时重复提交；三份正文与其余
 * 材料都在向导里补，这里不做成密集表单。
 */
export function NewDraftStart({ playerId }: { readonly playerId: string }) {
  const navigate = useNavigate();
  const template = useAuthoringTemplate();
  const createDraft = useCreateDraft();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [avatarFailed, setAvatarFailed] = useState(false);

  const nameLimit = template.data?.limits.display_name ?? 80;
  const descriptionLimit = template.data?.limits.description ?? 8000;
  const trimmedName = name.trim();
  const trimmedDescription = description.trim();
  const canStart = trimmedName !== '' && trimmedDescription !== '' && !createDraft.isPending;

  const start = () => {
    if (!canStart) return;
    // 预览头像用随机标识取色；真正草稿在提交时由 hook 生成编号。
    void createDraft
      .mutateAsync({
        playerId,
        displayName: trimmedName,
        description: trimmedDescription,
        avatarUrl: avatarUrl.trim() === '' ? null : avatarUrl.trim(),
      })
      .then((draft) => {
        navigate(`/app/characters/authoring/${draft.draft_id}`, { replace: true });
      })
      .catch(() => {
        // 错误在卡片内呈现，保留输入以便重试。
      });
  };

  return (
    <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-3 py-8 sm:px-6 sm:py-10">
      <div className="paper-sheet paper-zone animate-rise-in p-5 sm:p-8">
        <p className="text-[12px] font-medium uppercase tracking-[0.2em] text-accent">
          翻开一本新的人物志
        </p>
        <h1 className="mt-2 text-xl font-semibold">先告诉我，TA 是谁？</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-content-faint">
          一个名字、一两句话就够开始。动机、说话方式、经历和采访都可以在后面慢慢补，也可以全程自己手写。
        </p>

        <div className="mt-7 flex items-start gap-6">
          <div className="flex shrink-0 flex-col items-center gap-2">
            <div className="relative -rotate-1 rounded-[3px] bg-white/70 p-2 shadow-[0_10px_24px_-12px_rgba(60,40,20,.5)] transition-transform hover:rotate-0">
              <img
                src="/assets/decorations/paperclip.svg"
                alt=""
                aria-hidden="true"
                className="absolute -top-2.5 left-1/2 z-10 w-6 -translate-x-1/2 rotate-[12deg] opacity-80"
              />
              <CharacterAvatar
                identity={trimmedName === '' ? 'new-draft-preview' : `new-draft:${trimmedName}`}
                name={trimmedName === '' ? '?' : trimmedName}
                imageUrl={avatarUrl.trim() === '' || avatarFailed ? null : avatarUrl.trim()}
                onImageError={() => setAvatarFailed(true)}
                size="xl"
              />
            </div>
            <span className="text-[10px] text-content-faint">头像随名字取色</span>
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium text-content-muted">
                名字 <span className="text-danger">*</span>
              </span>
              <input
                value={name}
                maxLength={nameLimit}
                onChange={(event) => setName(event.target.value)}
                placeholder="比如：阿岚"
                className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2.5 text-sm outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium text-content-muted">
                一两句话描述 <span className="text-danger">*</span>
              </span>
              <textarea
                value={description}
                maxLength={descriptionLimit}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="深夜食堂门口总坐在同一张桌子的人，话不多，但什么都看在眼里。"
                rows={4}
                className="resize-none rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2.5 text-sm leading-relaxed outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
              />
              <span className="tabular self-end text-[10px] text-content-faint">
                {description.length}/{descriptionLimit}
              </span>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium text-content-muted">
                头像图片地址 <span className="text-content-faint">（可留空）</span>
              </span>
              <input
                value={avatarUrl}
                onChange={(event) => {
                  setAvatarUrl(event.target.value);
                  setAvatarFailed(false);
                }}
                placeholder="https://…"
                className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-sm outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
              />
              {avatarFailed ? (
                <span className="text-[10px] text-warn">图片无法加载，将使用名字首字头像。</span>
              ) : null}
            </label>
          </div>
        </div>

        {createDraft.isError ? (
          <div className="mt-5">
            <ErrorNotice error={createDraft.error} />
          </div>
        ) : null}

        <div className="mt-7 flex items-center justify-between gap-4">
          <p className="max-w-sm text-[11px] leading-relaxed text-content-faint">
            {template.data?.material_notice ?? '故事与采访会独立保存，运行时使用确认后的人物正文。'}
          </p>
          <button
            type="button"
            disabled={!canStart}
            onClick={start}
            className="shrink-0 rounded-lg bg-accent px-5 py-2.5 text-[13px] font-semibold text-accent-ink transition-[filter,transform] hover:brightness-110 active:scale-[0.98] disabled:opacity-40"
          >
            {createDraft.isPending ? '正在翻开…' : '开始创作'}
          </button>
        </div>
      </div>
    </div>
  );
}
