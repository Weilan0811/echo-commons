import { EmptyState } from '@/components/EmptyState';

/** 步骤实现前的占位，保证向导骨架可独立编译与预览。 */
export function StepPlaceholder({
  title,
  description,
}: {
  readonly title: string;
  readonly description: string;
}) {
  return (
    <EmptyState title={title} description={description}>
      <span className="text-[11px] text-content-faint">本章即将接入</span>
    </EmptyState>
  );
}
