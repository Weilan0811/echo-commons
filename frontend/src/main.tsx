import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router';
import { router } from './router';
import './styles/index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 契约没有推送接口，页面数据由各查询按需轮询；失败不无限重试。
      retry: 1,
      refetchOnWindowFocus: true,
      staleTime: 0,
    },
    mutations: {
      retry: 0,
    },
  },
});

const container = document.getElementById('root');
if (container === null) throw new Error('缺少 #root 挂载点');

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);