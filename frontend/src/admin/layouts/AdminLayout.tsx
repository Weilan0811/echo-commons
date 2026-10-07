import { NavLink, Outlet } from 'react-router';
import { Shell } from '@/components/Shell';

/**
 * 管理员端布局。
 *
 * 管理端是诊断视图而不是用户界面：单栏、信息密度高、不参与主体的读取身份。
 * 它沿用同一外壳以共享配色与字体，但左侧不显示用户端导航，改用自己的一行。
 * 页面正文由 AdminPage 提供标题与留白，这里只负责导航与外框。
 */
export function AdminLayout() {
  return (
    <Shell section="admin" list={null}>
      <div className="flex min-h-0 flex-1 flex-col">
        <nav className="flex shrink-0 items-center gap-1 border-b border-border-subtle px-8 py-2.5">
          {ADMIN_LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end ?? false}
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

        <div className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
    </Shell>
  );
}

/**
 * 管理端入口。
 *
 * 顺序按管理接入文档：先发现社群，再沿社群进入成员、角色与会话。
 * 运行状态与连接属于环境事实，不在对象诊断里，单独列出。
 */
const ADMIN_LINKS: ReadonlyArray<{ to: string; label: string; end?: boolean }> = [
  { to: '/admin', label: '运行状态', end: true },
  { to: '/admin/communities', label: '社群' },
  { to: '/admin/players', label: '玩家' },
  { to: '/admin/connection', label: '连接' },
];