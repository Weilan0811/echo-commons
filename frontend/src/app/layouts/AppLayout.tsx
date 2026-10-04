import { Outlet, useLocation } from 'react-router';
import { Shell } from '@/components/Shell';

/**
 * 用户端布局：提供三栏外壳，舞台部分由各页面经 Outlet 填充。
 * 导航区由路径决定，聊天与游戏是并列的两项能力。
 */
export function AppLayout() {
  const { pathname } = useLocation();
  const section = pathname.startsWith('/app/games') ? 'games' : 'chat';

  // 列表栏需要会话或游戏数据源，接入前为空。
  return (
    <Shell section={section} list={null}>
      <Outlet />
    </Shell>
  );
}
