import { CharacterAvatar } from '@/components/CharacterAvatar';
import type { AuthoringDraft } from '@/api/authoring';
import { stageStatusLabel } from '@/lib/authoring';

/**
 * 贯穿创作全程的人物卡。
 *
 * 头像配色按草稿标识派生，定稿前后保持同一视觉身份；三章与正文审核状态
 * 常驻可见，作者不用回到某个步骤才知道哪里待复核。
 */
export function PersonaCard({ draft }: { readonly draft: AuthoringDraft }) {
  const stages = [
    { label: '基础人设', status: draft.workflow.basic },
    { label: '过去故事', status: draft.workflow.story },
    { label: '人物采访', status: draft.workflow.interview },
  ] as const;

  return (
    <section className="rounded-card border border-border-subtle bg-surface-overlay/50 p-5">
      <div className="flex items-center gap-4">
        <CharacterAvatar
          identity={`blueprint:${draft.draft_id}`}
          name={draft.content.display_name}
          imageUrl={draft.content.avatar_url}
          size="xl"
          glow
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold">{draft.content.display_name}</p>
          <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-content-faint">
            {draft.content.description.trim() === '' ? '还没有一句话描述' : draft.content.description}
          </p>
        </div>
      </div>

      <ul className="mt-4 flex flex-col gap-1.5">
        {stages.map((stage) => (
          <li key={stage.label} className="flex items-center gap-2 text-[11px]">
            <StatusDot status={stage.status} />
            <span className="text-content-muted">{stage.label}</span>
            <span className={'ml-auto ' + statusTextClass(stage.status)}>
              {stageStatusLabel(stage.status)}
            </span>
          </li>
        ))}
        <li className="flex items-center gap-2 border-t border-border-subtle pt-2 text-[11px]">
          <StatusDot status={draft.workflow.documents_review} />
          <span className="text-content-muted">运行正文</span>
          <span className={'ml-auto ' + statusTextClass(draft.workflow.documents_review)}>
            {draft.workflow.documents_review === 'accepted' ? '已审核' : '待审核'}
          </span>
        </li>
      </ul>

      <p className="tabular mt-3 text-[10px] text-content-faint">
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
      return 'bg-content-faint/50';
  }
}

function statusTextClass(status: string): string {
  switch (status) {
    case 'accepted':
      return 'text-ok';
    case 'review_required':
      return 'text-warn';
    default:
      return 'text-content-faint';
  }
}
