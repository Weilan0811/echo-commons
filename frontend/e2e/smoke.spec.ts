import { expect, test } from '@playwright/test';

/**
 * 端到端测试对真实后端运行，不使用桩服务。
 * 访问地址需与后端 cors_origins 中的来源一致，否则浏览器会拒绝请求。
 *
 * 用户端页面直接读取后端，因此聊天相关用例需要后端运行；
 * 管理端与布局断言不需要后端。
 */

test('用户端三栏布局可用', async ({ page }) => {
  await page.goto('/app/chat');
  await expect(page.getByRole('link', { name: '聊天' })).toBeVisible();
  await expect(page.getByRole('link', { name: '游戏' })).toBeVisible();
});

test('未选择身份时引导到主体与社群入口', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/chat');
  await expect(page.getByText('先选择身份', { exact: true })).toBeVisible();
});

test('界面不提供指定受众的入口', async ({ page }) => {
  // 后端已移除可见范围字段：消息对会话成员一律可见，需要私下沟通时另开私聊。
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/setup');
  await expect(page.getByRole('button', { name: '私有' })).toHaveCount(0);
});

test('游戏列表显示未接入的空状态', async ({ page }) => {
  await page.goto('/app/games');
  await expect(page.getByText('还没有可玩的玩法')).toBeVisible();
});

test('主体与社群入口说明本地测试身份', async ({ page }) => {
  await page.goto('/app/setup');
  await expect(page.getByRole('heading', { name: '主体与社群' })).toBeVisible();
  await expect(page.getByText(/没有账户认证/)).toBeVisible();
});

test('主体与社群入口可保存本地身份', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/setup');

  await page.getByLabel('玩家标识').fill('probe-player');
  await page.getByLabel('显示名称').fill('探测');
  await page.getByRole('button', { name: '保存并进入' }).click();

  await expect(page).toHaveURL(/\/app\/chat$/);
  await expect(page.getByText('探测')).toBeVisible();
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

test('后端不可达时点明跨域拒绝并显示页面来源', async ({ page }) => {
  await page.goto('/admin/connection');
  await page.route('**/health/**', (route) => route.abort());

  await expect(page.getByRole('alert')).toContainText('无法连接后端或被跨域策略拒绝');
  await expect(page.getByRole('alert')).toContainText('http://127.0.0.1:8765');
});

test('缺少身份时聊天页不请求后端', async ({ page }) => {
  let requested = false;
  await page.addInitScript(() => window.localStorage.clear());
  await page.route('**/api/conversations?*', (route) => {
    requested = true;
    return route.continue();
  });

  await page.goto('/app/chat');
  await expect(page.getByText('先选择身份', { exact: true })).toBeVisible();
  expect(requested).toBe(false);
});
