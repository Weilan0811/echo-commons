import { Outlet } from 'react-router';

/**
 * 用户端路由的分组元素。各页面自行渲染三栏外壳，
 * 因为列表栏内容由页面自身的数据来源决定。
 */
export function AppLayout() {
  return <Outlet />;
}
