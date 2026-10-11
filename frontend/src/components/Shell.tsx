import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {
  Building2,
  ChevronDown,
  Drama,
  Gamepad2,
  IdCard,
  MessageCircle,
  Sun,
  Users,
} from 'lucide-react';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { useCommunity, useJoinedCommunities } from '@/api/directory';
import { SceneBackground } from './SceneBackground';

/**
 * 外壳区域。
 *
 * chat 与 games 是用户端的并列能力，各自带左侧会话/游戏列表；subject 是
 * 身份、社群与角色三个主体页；admin 是独立诊断视图，保持不透明后台外观，
 * 不铺场景背景、不显示玩家导航。
 */
export type ShellSection = 'chat' | 'games' | 'subject' | 'admin';

interface ShellProps {
  /** 当前区域，决定导航高亮与管理端分支。 */
  readonly section: ShellSection;
  /** 列表栏内容：会话列表或游戏列表；不需要时为 null。 */
  readonly list: ReactNode;
  /** 主舞台：消息流与输入器、游戏桌面，或诊断内容。 */
  readonly children: ReactNode;
  /**
   * 窄屏下列表收起为抽屉时的开关状态。不传则列表只按桌面常驻布局渲染。
   * 选择列表项后由调用方负责收起。
   */
  readonly mobileList?: {
    readonly open: boolean;
    readonly onOpenChange: (open: boolean) => void;
  };
}

/**
 * 玩家端外壳：场景背景上悬浮的玻璃卡片。
 *
 * 左栏是全局导航；列表栏与主舞台是两张独立玻璃卡，中间留缝，让背景从缝里
 * 透出，而不是一整块封闭的功能容器。区域差异只体现在布局上，不承担访问
 * 控制；隐藏导航不构成权限边界，见 adr/0003。
 */
export function Shell({ section, list, children, mobileList }: ShellProps) {
  if (section === 'admin') {
    return (
      <div className="flex h-screen flex-col overflow-hidden bg-surface-sunken">
        <header className="flex shrink-0 items-center gap-2 border-b border-border-subtle px-5 py-2.5">
          <span className="text-sm font-semibold tracking-wide">Echo Commons</span>
          <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[11px] text-content-muted">
            管理端
          </span>
        </header>
        <main className="flex min-h-0 flex-1 flex-col bg-surface">{children}</main>
      </div>
    );
  }

  return (
    <div className="relative flex h-screen gap-2.5 overflow-hidden p-2.5">
      <SceneBackground />
      <PlayerNav />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2.5">
        <TopBar
          listOpen={mobileList?.open ?? false}
          onOpenList={
            mobileList === undefined
              ? undefined
              : () => {
                  mobileList.onOpenChange(true);
                }
          }
        />
        <div className="flex min-h-0 flex-1 gap-2.5">
          {list === null ? null : (
            <>
              {mobileList?.open ? (
                <button
                  type="button"
                  aria-label="关闭列表"
                  onClick={() => {
                    mobileList.onOpenChange(false);
                  }}
                  className="fixed inset-0 z-30 bg-black/50 backdrop-blur-[2px] lg:hidden"
                />
              ) : null}
              <aside
                className={`glass-panel w-[300px] shrink-0 overflow-hidden rounded-card max-lg:fixed max-lg:inset-y-2.5 max-lg:left-2.5 max-lg:z-40 max-lg:w-[min(320px,calc(100vw_-_1.25rem))] max-lg:transition-transform max-lg:duration-200 ${
                  mobileList?.open
                    ? 'max-lg:translate-x-0'
                    : 'max-lg:-translate-x-[calc(100%_+_1.25rem)]'
                }`}
              >
                {list}
              </aside>
            </>
          )}
          <main className="glass-panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-card">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

/**
 * 玩家端全局左栏。
 *
 * 聊天、社群、角色、身份是四个常去的地方，游戏入口保留在导航中，活动模块
 * 上线前指向空态页。顶部蛾子是品牌，底部小字收住整栏。
 */
function PlayerNav() {
  return (
    <nav className="glass-panel flex w-[68px] shrink-0 flex-col items-center rounded-card py-4">
      <img
        src="/assets/brand/moth-mark-icon.svg"
        alt="Echo Commons"
        className="mb-5 h-9 w-auto"
      />
      <div className="flex flex-col items-center gap-1.5">
        {PLAYER_NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end ?? false}
            className={({ isActive }) =>
              `flex w-[54px] flex-col items-center gap-1 rounded-2xl py-2 text-[11px] transition-colors ${
                isActive
                  ? 'bg-accent-soft text-accent'
                  : 'text-content-faint hover:bg-white/5 hover:text-content-muted'
              }`
            }
          >
            <item.Icon className="size-[21px]" strokeWidth={1.7} />
            {item.label}
          </NavLink>
        ))}
      </div>
      <div className="mt-auto flex flex-col items-center gap-1.5">
        <img src="/assets/brand/moth-mark-icon.svg" alt="" className="h-5 w-auto opacity-50" />
        <span className="text-[9px] leading-tight tracking-[0.18em] text-content-faint">
          Echo
          <br />
          Commons
        </span>
      </div>
    </nav>
  );
}

const PLAYER_NAV_ITEMS: ReadonlyArray<{
  to: string;
  label: string;
  end?: boolean;
  Icon: typeof MessageCircle;
}> = [
  { to: '/app/chat', label: '聊天', Icon: MessageCircle },
  { to: '/app/communities', label: '社群', Icon: Users },
  { to: '/app/characters', label: '角色', Icon: Drama },
  { to: '/app/identity', label: '身份', Icon: IdCard },
  { to: '/app/games', label: '游戏', Icon: Gamepad2 },
];

/** 顶栏：窄屏列表入口与 tagline，右侧社群切换、世界时间与当前身份。透明地浮在背景上。 */
function TopBar({
  listOpen,
  onOpenList,
}: {
  readonly listOpen: boolean;
  readonly onOpenList?: (() => void) | undefined;
}) {
  const { subject } = useCurrentSubject();
  const showCommunity = subject.playerId !== '' && subject.communityId !== null;
  const community = useCommunity(subject.playerId, showCommunity ? subject.communityId : null);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 px-3">
      <div className="flex min-w-0 items-center gap-3">
        {onOpenList !== undefined ? (
          <button
            type="button"
            onClick={onOpenList}
            className={`glass-soft flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] transition-colors lg:hidden ${
              listOpen ? 'text-content' : 'text-content-muted hover:text-content'
            }`}
          >
            <MessageCircle className="size-3.5" strokeWidth={1.8} />
            会话
          </button>
        ) : null}
        <p className="hidden truncate text-[12px] tracking-[0.14em] text-content-faint sm:block">
          让每个灵魂，都能被听见
        </p>
      </div>

      <div className="flex items-center gap-3">
        {showCommunity && community.data !== undefined ? (
          <span
            className="flex items-center gap-1.5 text-[11px] text-content-muted"
            title={`社群世界时间（${community.data.timezone}）`}
          >
            <Sun className="size-3.5 text-accent" strokeWidth={1.8} />
            <span className="tabular">
              {formatWorldTime(community.data.world_time_utc, community.data.timezone)}
            </span>
          </span>
        ) : null}

        {subject.playerId !== '' ? <CommunitySwitcher /> : null}

        {subject.playerId === '' ? (
          <NavLink
            to="/app/identity"
            className="rounded-full bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink transition-[filter] hover:brightness-110"
          >
            登记身份
          </NavLink>
        ) : (
          <NavLink
            to="/app/identity"
            title="切换身份"
            className="glass-soft flex items-center gap-2 rounded-full py-1 pl-2.5 pr-3 text-[12px] text-content-muted transition-colors hover:text-content"
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
  );
}

/**
 * 社群切换器。
 *
 * 列出已加入的社群，选中即切换当前主体的社群上下文，不离开当前页面；
 * 会话列表等下游按 subject 自动刷新。管理入口去社群页。
 */
function CommunitySwitcher() {
  const { subject, set } = useCurrentSubject();
  const joined = useJoinedCommunities(subject.playerId);
  const items = joined.data?.items ?? [];

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="glass-soft flex items-center gap-2 rounded-full py-1.5 pl-3 pr-2.5 text-[12px] text-content outline-none transition-colors hover:text-content data-[state=open]:text-content"
        >
          <Building2 className="size-3.5 text-accent" strokeWidth={1.8} />
          <span className="max-w-[160px] truncate">{subject.communityName ?? '选择社群'}</span>
          <ChevronDown className="size-3.5 text-content-faint" strokeWidth={2} />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="glass-panel z-50 min-w-[220px] rounded-card p-1.5"
        >
          <p className="px-2.5 pb-1 pt-1.5 text-[10px] uppercase tracking-widest text-content-faint">
            我的世界
          </p>
          {items.length === 0 ? (
            <p className="px-2.5 py-1.5 text-[12px] text-content-faint">还没有加入社群</p>
          ) : (
            items.map((community) => {
              const active = community.community_id === subject.communityId;
              return (
                <DropdownMenu.Item
                  key={community.community_id}
                  onSelect={() => {
                    set({ communityId: community.community_id, communityName: community.name });
                  }}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none transition-colors data-[highlighted]:bg-white/8 ${
                    active ? 'text-accent' : 'text-content-muted'
                  }`}
                >
                  <Building2 className="size-3.5 shrink-0" strokeWidth={1.8} />
                  <span className="min-w-0 flex-1 truncate">{community.name}</span>
                  {active ? (
                    <span className="text-[10px] text-content-faint">当前</span>
                  ) : null}
                </DropdownMenu.Item>
              );
            })
          )}
          <DropdownMenu.Separator className="my-1 h-px bg-white/8" />
          <DropdownMenu.Item asChild>
            <NavLink
              to="/app/communities"
              className="flex cursor-pointer items-center rounded-lg px-2.5 py-2 text-[12px] text-content-faint outline-none transition-colors data-[highlighted]:bg-white/8 data-[highlighted]:text-content-muted"
            >
              管理社群
            </NavLink>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
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
