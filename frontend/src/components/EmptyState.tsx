import type { ReactNode } from 'react';

interface EmptyStateProps {
  readonly title: string;
  readonly description?: string;
  /** 事实性说明，用于解释为何当前为空，不提供虚假内容。 */
  readonly children?: ReactNode;
}

/**
 * 空状态。
 *
 * 用于尚未接入或没有内容的区域。说明必须是事实，不暗示功能可用，
 * 也不展示示例数据充当内容。
 */
export function EmptyState({ title, description, children }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-8 text-center">
      <p className="text-sm font-medium text-content-muted">{title}</p>
      {description !== undefined ? (
        <p className="max-w-sm text-xs leading-relaxed text-content-faint">{description}</p>
      ) : null}
      {children}
    </div>
  );
}
