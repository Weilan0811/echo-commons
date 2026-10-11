import { useState } from 'react';
import {
  useConfirmDraft,
  type AuthoringDraft,
  type CustomBlueprint,
} from '@/api/authoring';
import { ErrorNotice } from '@/components/ErrorNotice';

/**
 * 最终固定面板。
 *
 * 这是一次不可逆动作：确认后产生 custom: 人物资源，草稿不再可编辑，只能复制
 * 为新草稿。名字与头像在流程内的后果不同，末端分别说明，不笼统提示「不能改」。
 */
export function FinalizePanel({
  playerId,
  draft,
  fixedNotice,
  canFinalize,
  blockers,
  onConfirmed,
}: {
  readonly playerId: string;
  readonly draft: AuthoringDraft;
  readonly fixedNotice: string;
  readonly canFinalize: boolean;
  readonly blockers: readonly string[];
  readonly onConfirmed: (blueprint: CustomBlueprint) => void;
}) {
  const confirm = useConfirmDraft(playerId, draft.draft_id);
  const [acknowledged, setAcknowledged] = useState(false);

  return (
    <div className="relative overflow-hidden rounded-card border border-accent/30 bg-gradient-to-b from-accent-soft/40 to-surface-overlay/30 p-5">
      <div className="flex items-center gap-2.5">
        <LockIcon />
        <h3 className="text-[15px] font-semibold">定格人物</h3>
      </div>
      <p className="mt-2.5 text-[12px] leading-relaxed text-content-muted">{fixedNotice}</p>

      <ul className="mt-3 flex flex-col gap-1.5 text-[11px] leading-relaxed text-content-faint">
        <li className="flex gap-2">
          <span className="text-accent">·</span>
          <span>
            <span className="text-content-muted">名字：</span>
            固定前若回「初识」改名，需要重新审核正文并重建采访依据；固定后只能复制成新草稿才能修改。
          </span>
        </li>
        <li className="flex gap-2">
          <span className="text-accent">·</span>
          <span>
            <span className="text-content-muted">头像：</span>
            更换头像不影响流程状态；固定后同样只能通过复制新草稿更换。
          </span>
        </li>
        <li className="flex gap-2">
          <span className="text-accent">·</span>
          <span>固定不影响其他副本与既有实例；实例各自保存状态、关系与记忆。</span>
        </li>
      </ul>

      {canFinalize ? (
        <div className="mt-4 flex flex-col gap-3">
          <label className="flex items-start gap-2 text-[12px] text-content-muted">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              className="mt-0.5 accent-amber-500"
            />
            <span>我已知悉：固定后人物内容不可编辑，只能复制为新草稿继续修改。</span>
          </label>
          {confirm.isError ? <ErrorNotice error={confirm.error} /> : null}
          <button
            type="button"
            disabled={!acknowledged || confirm.isPending}
            onClick={() => {
              void confirm
                .mutateAsync(draft.revision)
                .then((blueprint) => {
                  setAcknowledged(false);
                  onConfirmed(blueprint);
                })
                .catch(() => undefined);
            }}
            className="self-start rounded-lg bg-accent px-5 py-2 text-[13px] font-semibold text-accent-ink shadow-[0_0_20px_rgba(245,158,11,0.25)] transition-[filter,transform] hover:brightness-110 active:scale-[0.99] disabled:opacity-40 disabled:shadow-none"
          >
            {confirm.isPending ? '定格中…' : '定格人物'}
          </button>
        </div>
      ) : (
        <div className="mt-4 rounded-lg border border-border-subtle bg-surface-sunken/60 p-3">
          <p className="text-[12px] font-medium text-content-muted">定格前还差几步</p>
          <ul className="mt-1.5 list-disc pl-5 text-[11px] leading-relaxed text-warn">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function LockIcon() {
  return (
    <span className="flex size-7 items-center justify-center rounded-full bg-accent/15 text-accent">
      <svg viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.6}>
        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
        <path d="M5.5 7V5.5a2.5 2.5 0 0 1 5 0V7" strokeLinecap="round" />
      </svg>
    </span>
  );
}
