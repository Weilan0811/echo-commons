import { CharacterAvatar } from '@/components/CharacterAvatar';
import type { AuthoringDraft } from '@/api/authoring';
import { stageStatusLabel } from '@/lib/authoring';

/**
 * 贯穿创作全程的人物拍立得。
 *
 * 位于信纸右侧：头像/肖像、名字与一句话描述，三章与正文审核状态常驻可见，
 * 作者不用回到某个步骤才知道哪里待复核。头像配色按草稿标识派生，定稿前后
 * 保持同一视觉身份。回形针只在拍立得上使用一次，装饰不蔓延到信纸内部。
 */
export function PersonaCard({ draft }: { readonly draft: AuthoringDraft }) {
  const stages = [
    { label: '基础人设', status: draft.workflow.basic },
    { label: '过去故事', status: draft.workflow.story },
    { label: '人物采访', status: draft.workflow.interview },
  ] as const;

  return (
    <section className="paper-sheet paper-zone relative -rotate-1 p-3 pb-4 transition-transform duration-300 hover:rotate-0">
      <img
        src="/assets/decorations/paperclip.svg"
        alt=""
        aria-hidden="true"
        className="absolute -top-3 left-1/2 z-10 w-7 -translate-x-1/2 rotate-[10deg] opacity-80"
      />
      <div className="relative flex aspect-square items-center justify-center overflow-hidden rounded-[3px] bg-[color-mix(in_oklch,var(--color-paper)_72%,white)]">
        {draft.content.avatar_url !== null && draft.content.avatar_url !== '' ? (
          <img
            src={draft.content.avatar_url}
            alt={draft.content.display_name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <CharacterAvatar
            identity={`blueprint:${draft.draft_id}`}
            name={draft.content.display_name}
            size="xl"
          />
        )}
      </div>

      <p className="mt-3 truncate text-center text-[17px] font-semibold text-ink">
        {draft.content.display_name.trim() === '' ? '还没有名字' : draft.content.display_name}
      </p>
      <p className="mt-1 line-clamp-2 min-h-7 px-1 text-center text-[11px] leading-relaxed text-ink-faint">
        {draft.content.description.trim() === '' ? '一两句话描述会出现在这里' : draft.content.description}
      </p>

      <ul className="mt-4 flex flex-col gap-1.5 border-t border-ink/15 px-1 pt-3">
        {stages.map((stage) => (
          <li key={stage.label} className="flex items-center gap-2 text-[11px]">
            <StatusDot status={stage.status} />
            <span className="text-ink-muted">{stage.label}</span>
            <span className={'ml-auto ' + statusTextClass(stage.status)}>
              {stageStatusLabel(stage.status)}
            </span>
          </li>
        ))}
        <li className="flex items-center gap-2 border-t border-ink/10 pt-2 text-[11px]">
          <StatusDot status={draft.workflow.documents_review} />
          <span className="text-ink-muted">运行正文</span>
          <span className={'ml-auto ' + statusTextClass(draft.workflow.documents_review)}>
            {draft.workflow.documents_review === 'accepted' ? '已审核' : '待审核'}
          </span>
        </li>
      </ul>

      <p className="tabular mt-3 px-1 text-center text-[10px] text-ink-faint">
        草稿版本 r{draft.revision}
        {draft.confirmed_blueprint_id !== null ? ' · 已固定' : ''}
      </p>
    </section>
  );
}

function StatusDot({ status }: { readonly status: string }) {
  const pulse = status === 'review_required' ? ' animate-breathe' : '';
  return (
    <span
      className={`inline-block size-1.5 shrink-0 rounded-full${pulse} ${dotClass(status)}`}
      aria-hidden="true"
    />
  );
}

function dotClass(status: string): string {
  switch (status) {
    case 'accepted':
      return 'bg-ok';
    case 'review_required':
      return 'bg-warn';
    default:
      return 'bg-ink-faint/50';
  }
}

function statusTextClass(status: string): string {
  switch (status) {
    case 'accepted':
      return 'text-ok';
    case 'review_required':
      return 'text-warn';
    default:
      return 'text-ink-faint';
  }
}
