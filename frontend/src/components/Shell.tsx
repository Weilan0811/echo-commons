import type { ReactNode } from 'react';
import { NavLink } from 'react-router';

interface ShellProps {
  readonly area: string;
  readonly navItems: ReadonlyArray<{ to: string; label: string; end?: boolean }>;
  readonly children: ReactNode;
}

/**
 * 两套路由树共用的外壳，只负责区域标识与导航。
 * 区域差异由布局体现；访问边界不由隐藏导航承担，见 adr/0003。
 */
export function Shell({ area, navItems, children }: ShellProps) {
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4">
      <header className="flex items-baseline justify-between border-b border-border-subtle py-4">
        <div className="flex items-baseline gap-3">
          <span className="text-base font-semibold">Echo Commons</span>
          <span className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-content-muted">
            {area}
          </span>
        </div>
        <nav className="flex gap-1 text-sm">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end ?? false}
              className={({ isActive }) =>
                `rounded px-2 py-1 ${
                  isActive
                    ? 'bg-surface-muted font-medium'
                    : 'text-content-muted hover:text-content'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="flex-1 py-6">{children}</main>
    </div>
  );
}