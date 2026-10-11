import type { ReactNode } from 'react';

/**
 * 玻璃面板。
 *
 * 玻璃代表当下的交流与操作：会话列表、会话头部、输入条、设置表单与弹窗。
 * 材质规格集中在 index.css 的 .glass-panel，这里只负责语义封装，调用方
 * 通过 className 决定圆角、内边距与布局，不另造变体。
 */
export function GlassPanel({
  children,
  className = '',
}: {
  readonly children: ReactNode;
  readonly className?: string;
}) {
  return <div className={`glass-panel ${className}`}>{children}</div>;
}
