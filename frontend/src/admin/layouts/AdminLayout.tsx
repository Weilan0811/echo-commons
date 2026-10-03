import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';

/** 管理员端布局：测试管理与运行事实查看。 */
export function AdminLayout() {
  return (
    <Shell
      area="管理员端"
      navItems={[
        { to: '/admin', label: '运行概况', end: true },
        { to: '/app', label: '用户端' },
      ]}
    >
      <Outlet />
    </Shell>
  );
}