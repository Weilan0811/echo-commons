import type { ReactNode } from 'react';

/**
 * 纸张。
 *
 * 纸张代表被书写和珍藏的故事：创作信纸、人物档案。材质（暖米渐变、细颗粒、
 * 投影）集中在 index.css 的 .paper-sheet。纸面内部靠留白与排版分层，
 * 不要再嵌套厚重卡片。
 */
export function PaperSheet({
  children,
  className = '',
}: {
  readonly children: ReactNode;
  readonly className?: string;
}) {
  return <div className={`paper-sheet ${className}`}>{children}</div>;
}
