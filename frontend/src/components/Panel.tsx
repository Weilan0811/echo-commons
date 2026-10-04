import type { ReactNode } from 'react';

interface PanelProps {
  readonly title: string;
  readonly description?: string;
  readonly children: ReactNode;
}

/**
 * 内容区块。信息密度按页面需要调整，不在此固定视觉规格。
 *
 * 用于诊断与设置类内容；聊天与游戏界面不使用该区块，
 * 避免界面呈现管理页形态。
 */
export function Panel({ title, description, children }: PanelProps) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface-raised">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description === undefined ? null : (
          <p className="mt-0.5 text-xs text-content-faint">{description}</p>
        )}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}
