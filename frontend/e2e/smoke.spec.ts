import { expect, test } from '@playwright/test';

/**
 * 端到端测试对真实后端运行，不使用桩服务。
 * 访问地址需与后端 cors_origins 中的来源一致，否则浏览器会拒绝请求。
 *
 * 用户端页面当前使用临时预览数据，其中不依赖后端的用例可以立即运行；
 * 读取健康状态的用例需要后端启动。
 */

const list = (page: import('@playwright/test').Page) => page.getByRole('navigation', { name: '会话列表' });
const thread = (page: import('@playwright/test').Page) => page.getByRole('log', { name: '消息' });

test('用户端三栏布局可用', async ({ page }) => {
  await page.goto('/app/chat');
  await expect(page.getByRole('link', { name: '聊天' })).toBeVisible();
  await expect(page.getByRole('link', { name: '游戏' })).toBeVisible();
});

test('会话列表区分群聊与私聊', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');

  await expect(list(page).getByText('群聊', { exact: true })).toBeVisible();
  await expect(list(page).getByText('私聊', { exact: true })).toBeVisible();
  await expect(list(page).getByText('小槿')).toBeVisible();
});

test('消息按发送者分组渲染', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');

  await expect(thread(page).getByText('大家还没睡？')).toBeVisible();
  await expect(thread(page).getByText('那家面馆十一点才开门')).toBeVisible();
  // 角色名只在组首出现一次
  await expect(thread(page).getByText('小槿', { exact: true })).toHaveCount(1);
});

test('长消息拆成多个气泡', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');
  // 小槿的长回应被拆成两块，正文仍然完整
  await expect(thread(page).getByText(/翻到很早以前的那张夜市/)).toBeVisible();
  await expect(thread(page).getByText(/里居然有你/)).toBeVisible();
});

test('私有消息带标记，与输入器的私有按钮区分', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');
  await expect(thread(page).locator('[title="仅指定受众可见"]')).toHaveCount(1);
});

test('提及显示角色名称而不是标识', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');
  await expect(thread(page).getByText(/@阿澈/)).toBeVisible();
  await expect(thread(page).getByText(/@preview-/)).toHaveCount(0);
});

test('序号不连续时不渲染缺口占位', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');
  const body = await thread(page).innerText();
  expect(body).not.toMatch(/跳过|缺失|不可见|序号/);
});

test('轮次状态栏区分正在回应、沉默与失败', async ({ page }) => {
  await page.goto('/app/chat/preview-conv-group');

  await expect(page.getByText(/正在回应/)).toBeVisible();
  await expect(page.getByText(/选择沉默/)).toBeVisible();
  await expect(page.getByText(/回应失败/)).toBeVisible();
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
