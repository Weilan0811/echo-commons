import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';

/** 用户端布局：最终用户的日常页面。 */
export function AppLayout() {
  return (
    <Shell area="用户端" navItems={[{ to: '/app', label: '连接', end: true }]}>
      <Outlet />
    </Shell>
  );
}