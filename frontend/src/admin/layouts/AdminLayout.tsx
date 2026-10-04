import { Outlet } from 'react-router';
import { Shell } from '@/components/Shell';

/**
 * 管理员端布局。管理端是单栏诊断视图，不使用会话列表栏，
 * 但沿用同一外壳以共享顶栏与配色。
 */
export function AdminLayout() {
  return (
    <Shell section="admin" list={null}>
      <Outlet />
    </Shell>
  );
}
