import { Outlet } from 'react-router';
import { CommunityRealtime } from '@/api/realtime';
import { useCurrentSubject } from '@/identity/useCurrentSubject';

/**
 * 用户端路由的分组元素。各页面自行渲染三栏外壳，
 * 因为列表栏内容由页面自身的数据来源决定。
 */
export function AppLayout() {
  const { subject } = useCurrentSubject();
  return subject.playerId && subject.communityId
    ? <CommunityRealtime key={JSON.stringify([subject.playerId, subject.communityId])} playerId={subject.playerId} communityId={subject.communityId}><Outlet /></CommunityRealtime>
    : <Outlet />;
}
