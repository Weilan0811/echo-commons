import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { useCommunity } from '@/api/directory';

/**
 * 外壳区域。
 *
 * chat 与 games 是用户端的并列能力，各自带左侧窄栏切换。
 * subject 是身份、社群与角色三个主体页：它们不是聊天也不是游戏，显示窄栏
 * 会让「聊天」一直高亮，看起来像当前就在聊天里。
 * admin 是独立诊断视图。
 */
export type ShellSection = 'chat' | 'games' | 'subject' | 'admin';

const NAV_ITEMS: ReadonlyArray<{ to: string; label: string; section: ShellSection }> = [
  { to: '/app/chat', label: '聊天', section: 'chat' },
  { to: '/app/games', label: '游戏', section: 'games' },
];

/**
 * 顶栏入口。
 *
 * 身份、社群与角色是使用者的三项前提，放在顶栏而不是左侧窄栏：窄栏已经
 * 承担聊天与游戏的主切换，再加三项会挤成一列图标，读不出文字。
 */
const SUBJECT_LINKS: ReadonlyArray<{ to: string; label: string }> = [
  { to: '/app/identity', label: '身份' },
  { to: '/app/communities', label: '社群' },
  { to: '/app/characters', label: '角色' },
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
  const showNav = section === 'chat' || section === 'games';
  const community = useCommunity(subject.playerId, showNav ? subject.communityId : null);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border-subtle bg-surface-sunken px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          {/*
           * 应用名同时是回聊天页的入口。主体页不显示左侧窄栏，没有这条
           * 路径就只能靠浏览器后退返回。
           */}
          <NavLink
            to="/app/chat"
            title="回到聊天"
            className={`shrink-0 text-sm font-semibold tracking-wide ${
              section === 'chat' ? 'text-content' : 'text-content-muted hover:text-content'
            }`}
          >
            Echo Commons
          </NavLink>
          {section === 'admin' ? (
            <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[11px] text-content-muted">
              管理端
            </span>
          ) : (
            <>
              <nav className="flex shrink-0 items-center gap-0.5 rounded-lg bg-surface-raised p-0.5">
                {SUBJECT_LINKS.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    className={({ isActive }) =>
                      `rounded-md px-2.5 py-1 text-[12px] transition-colors ${
                        isActive
                          ? 'bg-surface-overlay text-content'
                          : 'text-content-faint hover:text-content-muted'
                      }`
                    }
                  >
                    {link.label}
                  </NavLink>
                ))}
              </nav>
              <NavLink
                to="/app/communities"
                title="切换社群"
                className="truncate text-xs text-content-faint hover:text-content-muted"
              >
                {subject.communityName ?? subject.communityId ?? '未选择社群'}
              </NavLink>
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {showNav && community.data !== undefined ? (
            <span
              className="text-[11px] text-content-faint"
              title={`社群世界时间（${community.data.timezone}）`}
            >
              {formatWorldTime(community.data.world_time_utc, community.data.timezone)}
            </span>
          ) : null}

          {subject.playerId === '' ? (
            <NavLink
              to="/app/identity"
              className="rounded-lg bg-accent px-2.5 py-1 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110"
            >
              登记身份
            </NavLink>
          ) : (
            <NavLink
              to="/app/identity"
              className="flex items-center gap-2 rounded-lg px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-raised hover:text-content"
              title="切换身份"
            >
              <span
                className="inline-block size-2 rounded-full"
                style={{ backgroundColor: 'var(--color-accent)' }}
                aria-hidden="true"
              />
              {subject.playerDisplayName}
            </NavLink>
          )}
        </div>
      </header>

      {/*
       * 外围压暗、内容提亮：顶栏与导航栏用最暗的一档形成 L 形包围，列表栏
       * 居中，主舞台最亮。视线因此被收进对话本身，而不是被框架分走。
       */}
      <div className="flex min-h-0 flex-1">
        {showNav ? (
          <nav className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-border-subtle bg-surface-sunken py-3">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={`flex w-12 flex-col items-center gap-1 rounded-lg py-2 text-[11px] transition-colors ${
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
          <div className="flex min-h-0 w-64 shrink-0 flex-col border-r border-border-subtle bg-surface">
            {list}
          </div>
        )}

        <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface-raised">{children}</main>
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

/**
 * 社群世界时间。
 *
 * 社群有独立时间线，返回值不随本机时钟前进，因此这里只做格式化：
 * 按社群时区显示月日与时分，不用本机时间代替。
 */
function formatWorldTime(isoUtc: string, timezone: string): string {
  const parsed = new Date(isoUtc);
  if (Number.isNaN(parsed.getTime())) return '';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: timezone,
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(parsed);
  } catch {
    // 时区标识不被运行时识别时退回 UTC，不猜测本地时区。
    return `${parsed.getUTCMonth() + 1}月${parsed.getUTCDate()}日 ${pad(parsed.getUTCHours())}:${pad(parsed.getUTCMinutes())}`;
  }
}

function pad(value: number): string {
  return `${value}`.padStart(2, '0');
}
