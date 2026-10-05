import { createBrowserRouter, Navigate } from 'react-router';
import { AppLayout } from '@/app/layouts/AppLayout';
import { ChatPage } from '@/app/pages/ChatPage';
import { GamesPage } from '@/app/pages/GamesPage';
import { SetupPage } from '@/app/pages/SetupPage';
import { AdminLayout } from '@/admin/layouts/AdminLayout';
import { AdminHomePage } from '@/admin/pages/AdminHomePage';
import { ConnectionPage } from '@/admin/pages/ConnectionPage';
import { RouteErrorPage } from '@/components/RouteErrorPage';

/**
 * 单个应用承载两套路由树：/app 为用户端，/admin 为管理员端。
 * 两棵树共用接口客户端、通用组件与状态处理，见 adr/0003。
 */
export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/app/chat" replace /> },
  {
    path: '/app',
    element: <AppLayout />,
    errorElement: <RouteErrorPage />,
    children: [
      { index: true, element: <Navigate to="/app/chat" replace /> },
      { path: 'setup', element: <SetupPage /> },
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
    ],
  },
  { path: '*', element: <Navigate to="/app/chat" replace /> },
]);
