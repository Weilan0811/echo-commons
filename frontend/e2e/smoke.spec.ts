import { expect, test } from '@playwright/test';

/**
 * 端到端测试对真实后端运行，不使用桩服务。
 * 访问地址需与后端 cors_origins 中的来源一致，否则浏览器会拒绝请求。
 *
 * 本文件只放不写入后端数据的用例：身份保存、注册与聊天都在 chat.spec.ts。
 */

test('用户端三栏布局可用', async ({ page }) => {
  await page.goto('/app/chat');
  await expect(page.getByRole('link', { name: '聊天' })).toBeVisible();
  await expect(page.getByRole('link', { name: '游戏' })).toBeVisible();
});

test('侧栏提供身份、社群与角色入口', async ({ page }) => {
  await page.goto('/app/chat');
  const topNav = page.getByRole('navigation');
  await expect(topNav.getByRole('link', { name: '身份', exact: true })).toBeVisible();
  await expect(topNav.getByRole('link', { name: '社群', exact: true })).toBeVisible();
  await expect(topNav.getByRole('link', { name: '角色', exact: true })).toBeVisible();
});

test('未选择身份时引导登记', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/chat');
  await expect(page.getByText('先登记身份', { exact: true })).toBeVisible();
});

test('三个主体页面各自可达', async ({ page }) => {
  await page.goto('/app/identity');
  await expect(page.getByRole('heading', { level: 1, name: '身份登记' })).toBeVisible();
  await expect(page.getByText(/没有账户认证/)).toBeVisible();

  await page.goto('/app/communities');
  await expect(page.getByRole('heading', { level: 1, name: '社群' })).toBeVisible();

  await page.goto('/app/characters');
  await expect(page.getByRole('heading', { level: 1, name: '角色' })).toBeVisible();
  await expect(page.getByRole('button', { name: '创作自定义人物' })).toBeVisible();
});

test('界面不提供指定受众的入口', async ({ page }) => {
  // 后端已移除可见范围字段：消息对会话成员一律可见，需要私下沟通时另开私聊。
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/identity');
  await expect(page.getByRole('button', { name: '私有' })).toHaveCount(0);
});

test('游戏列表显示未接入的空状态', async ({ page }) => {
  await page.goto('/app/games');
  await expect(page.getByText('还没有可玩的玩法')).toBeVisible();
});

test('管理员端与用户端分开导航', async ({ page }) => {
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: '运行状态' })).toBeVisible();
});

test('管理端连接页读取后端存活状态', async ({ page }) => {
  await page.goto('/admin/connection');
  await expect(page.getByRole('heading', { name: '后端连接' })).toBeVisible();
  await expect(page.getByText('存活：ok')).toBeVisible();
  await expect(page.getByText('echo-commons-server')).toBeVisible();
});

test('就绪状态按真实返回展示后台工作进程', async ({ page }) => {
  await page.goto('/admin/connection');
  await expect(page.getByText('就绪：ready')).toBeVisible();
  await expect(page.getByText('social')).toBeVisible();
  await expect(page.getByText('[object Object]')).toHaveCount(0);
});

test('真实跨域拒绝时管理端显示来源，使用允许的来源后连接成功', async ({ page, baseURL }) => {
  const allowed = new URL(baseURL!);
  const rejected = new URL(allowed);
  rejected.hostname = allowed.hostname === 'localhost' ? '127.0.0.1' : 'localhost';
  // 两个地址访问同一前端，后端只允许验证配置中的页面来源。
  await page.goto(new URL('/admin/connection', rejected).href);
  await expect(page.getByRole('alert').first()).toContainText('无法连接后端或被跨域策略拒绝');
  await expect(page.getByRole('alert').first()).toContainText(new URL(page.url()).origin);
  await expect(page.getByRole('alert').first()).toContainText(process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765');
  await page.goto(new URL('/admin/connection', allowed).href);
  await expect(page.getByText('存活：ok')).toBeVisible();
});

test('缺少身份时聊天页不请求后端', async ({ page }) => {
  let requested = false;
  await page.addInitScript(() => window.localStorage.clear());
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/conversations') requested = true;
  });

  await page.goto('/app/chat');
  await expect(page.getByText('先登记身份', { exact: true })).toBeVisible();
  expect(requested).toBe(false);
});
