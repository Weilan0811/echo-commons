import type { ReactNode } from 'react';

/** 每章顶部标题区：序号、章名、一句说明与右侧动作位。 */
export function StepHeader({
  index,
  title,
  description,
  children,
}: {
  readonly index: number;
  readonly title: string;
  readonly description: string;
  readonly children?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-accent">
          第 {index + 1} 章
        </p>
        <h2 className="mt-1 text-lg font-semibold">{title}</h2>
        <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-content-faint">{description}</p>
      </div>
      {children}
    </header>
  );
}

/** 步骤内的地带标题，用来区分「作者原稿」与「人物正文」。 */
export function ZoneHeading({
  title,
  hint,
  children,
}: {
  readonly title: string;
  readonly hint: string;
  readonly children?: ReactNode;
}) {
  return (
    <div className="mb-2.5 flex items-center justify-between gap-3">
      <div>
        <h3 className="text-[12px] font-semibold text-content-muted">{title}</h3>
        <p className="mt-0.5 text-[10px] text-content-faint">{hint}</p>
      </div>
      {children}
    </div>
  );
}

/** 章末动作条：保存与章节确认等主动作集中在右侧。 */
export function StepActionBar({ children }: { readonly children: ReactNode }) {
  return (
    <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-3 rounded-lg border border-border-subtle bg-surface-raised/90 px-4 py-3 backdrop-blur">
      {children}
    </div>
  );
}

/** 小型阶段状态徽标。 */
export function StageBadge({ status }: { readonly status: 'pending' | 'accepted' | 'review_required' | 'unused' }) {
  const text = {
    pending: '未确认',
    accepted: '已定稿',
    review_required: '待复核',
    unused: '留白',
  }[status];
  const className = {
    pending: 'border-border-strong text-content-faint',
    accepted: 'border-ok/50 bg-ok/10 text-ok',
    review_required: 'border-warn/50 bg-warn/10 text-warn',
    unused: 'border-border-subtle text-content-faint',
  }[status];
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${className}`}>
      {text}
    </span>
  );
}
