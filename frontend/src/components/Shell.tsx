import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import { useCurrentSubject } from '@/identity/useCurrentSubject';

/** 外壳区域。聊天与游戏是用户端的并列能力，管理端为独立诊断视图。 */
export type ShellSection = 'chat' | 'games' | 'admin';

const NAV_ITEMS: ReadonlyArray<{ to: string; label: string; section: ShellSection }> = [
  { to: '/app/chat', label: '聊天', section: 'chat' },
  { to: '/app/games', label: '游戏', section: 'games' },
];

interface ShellProps {
  /** 当前区域，决定导航高亮。 */
  readonly section: ShellSection;
  /** 列表栏内容：会话列表或游戏列表；不需要时为空。 */
  readonly list: ReactNode;
  /** 主舞台：消息流与输入器、游戏桌面，或诊断内容。 */
  readonly children: ReactNode;
}

/**
 * 三栏外壳：顶栏、导航栏、列表栏与主舞台。
 *
 * 区域差异只体现在布局上，不承担访问控制；隐藏导航不构成权限边界，见 adr/0003。
 */
export function Shell({ section, list, children }: ShellProps) {
  const { subject } = useCurrentSubject();
  const showNav = section !== 'admin';

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border-subtle px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="shrink-0 text-sm font-semibold tracking-wide">Echo Commons</span>
          {showNav ? (
            <span className="truncate text-xs text-content-faint">
              {subject.communityName ?? subject.communityId ?? '未选择社群'}
            </span>
          ) : (
            <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[11px] text-content-muted">
              管理端
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {subject.playerId === '' ? (
            <NavLink
              to="/app/setup"
              className="rounded border border-border-strong px-2 py-1 text-xs text-content-muted hover:text-content"
            >
              选择身份
            </NavLink>
          ) : (
            <NavLink
              to="/app/setup"
              className="flex items-center gap-2 rounded px-1.5 py-1 text-xs text-content-muted hover:bg-surface-raised hover:text-content"
              title="切换身份或社群"
            >
              <span
                className="inline-block size-4 rounded-full"
                style={{ backgroundColor: 'var(--color-accent)' }}
                aria-hidden="true"
              />
              {subject.playerDisplayName}
            </NavLink>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {showNav ? (
          <nav className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border-subtle py-3">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={`flex w-12 flex-col items-center gap-1 rounded-md py-2 text-[11px] transition-colors ${
                  item.section === section
                    ? 'bg-surface-overlay text-content'
                    : 'text-content-faint hover:bg-surface-raised hover:text-content-muted'
                }`}
              >
                <SectionIcon section={item.section} />
                {item.label}
              </NavLink>
            ))}
          </nav>
        ) : null}

        {list === null ? null : (
          <div className="flex min-h-0 w-64 shrink-0 flex-col border-r border-border-subtle">
            {list}
          </div>
        )}

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</main>
      </div>
    </div>
  );
}

function SectionIcon({ section }: { readonly section: ShellSection }) {
  if (section === 'games') {
    return (
      <svg viewBox="0 0 20 20" className="size-4" aria-hidden="true" fill="none" strokeWidth={1.6}>
        <rect x="2.5" y="2.5" width="6" height="6" rx="1.2" stroke="currentColor" />
        <rect x="11.5" y="2.5" width="6" height="6" rx="3" stroke="currentColor" />
        <rect x="2.5" y="11.5" width="6" height="6" rx="3" stroke="currentColor" />
        <rect x="11.5" y="11.5" width="6" height="6" rx="1.2" stroke="currentColor" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" className="size-4" aria-hidden="true" fill="none" strokeWidth={1.6}>
      <path d="M3 4.5h14v9H8l-4 3v-3H3z" stroke="currentColor" strokeLinejoin="round" />
    </svg>
  );
}
