import { createBrowserRouter, Navigate } from 'react-router';
import { AppLayout } from '@/app/layouts/AppLayout';
import { ChatPage } from '@/app/pages/ChatPage';
import { GamesPage } from '@/app/pages/GamesPage';
import { IdentityPage } from '@/app/pages/IdentityPage';
import { CommunityPage } from '@/app/pages/CommunityPage';
import { CommunityDetailPage } from '@/app/pages/CommunityDetailPage';
import { CommunityCreatePage } from '@/app/pages/CommunityCreatePage';
import { CharacterPage } from '@/app/pages/CharacterPage';
import { AuthoringPage } from '@/app/pages/authoring/AuthoringPage';
import { AdminLayout } from '@/admin/layouts/AdminLayout';
import { AdminHomePage } from '@/admin/pages/AdminHomePage';
import { ConnectionPage } from '@/admin/pages/ConnectionPage';
import { AdminCommunityPage } from '@/admin/pages/AdminCommunityPage';
import { AdminCommunityDetailPage } from '@/admin/pages/AdminCommunityDetailPage';
import { AdminCharacterPage } from '@/admin/pages/AdminCharacterPage';
import { AdminConversationPage } from '@/admin/pages/AdminConversationPage';
import { AdminTaskPage } from '@/admin/pages/AdminTaskPage';
import { AdminPlayerPage } from '@/admin/pages/AdminPlayerPage';
import { RouteErrorPage } from '@/components/RouteErrorPage';

/**
 * 单个应用承载两套路由树：/app 为用户端，/admin 为管理员端。
 * 两棵树共用接口客户端、通用组件与状态处理，见 adr/0003。
 *
 * 管理端按管理接入文档的顺序组织：先社群，再沿社群进入会话、角色，最后到
 * 任务。角色页同时承载记忆与反思，因为它们都以角色为范围。
 */
export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/app/chat" replace /> },
  {
    path: '/app',
    element: <AppLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <Navigate to="/app/chat" replace /> },
      { path: 'identity', element: <IdentityPage /> },
      { path: 'communities', element: <CommunityPage /> },
      { path: 'communities/new', element: <CommunityCreatePage /> },
      { path: 'communities/:communityId', element: <CommunityDetailPage /> },
      { path: 'characters', element: <CharacterPage /> },
      { path: 'characters/authoring/:draftId', element: <AuthoringPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'chat/:conversationId', element: <ChatPage /> },
      { path: 'games', element: <GamesPage /> },
    ],
  },
  {
    path: '/admin',
    element: <AdminLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <AdminHomePage /> },
      { path: 'connection', element: <ConnectionPage /> },
      { path: 'communities', element: <AdminCommunityPage /> },
      { path: 'communities/:communityId', element: <AdminCommunityDetailPage /> },
      {
        path: 'communities/:communityId/conversations/:conversationId',
        element: <AdminConversationPage />,
      },
      {
        path: 'communities/:communityId/characters/:characterId',
        element: <AdminCharacterPage />,
      },
      {
        path: 'communities/:communityId/characters/:characterId/tasks/:taskId',
        element: <AdminTaskPage />,
      },
      { path: 'players', element: <AdminPlayerPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/app/chat" replace /> },
]);
