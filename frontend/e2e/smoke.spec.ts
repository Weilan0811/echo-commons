import { expect, test } from '@playwright/test';

/**
 * 冒烟测试对真实后端运行，不使用桩服务。
 * 访问地址需与后端 cors_origins 中的来源一致，否则浏览器会拒绝请求。
 * 运行前需要后端已启动，并在其 config/settings.toml 中放行前端来源。
 */

test('用户端连接页读取后端存活状态', async ({ page }) => {
  await page.goto('/app');

  await expect(page.getByRole('heading', { name: '后端连接' })).toBeVisible();
  await expect(page.getByText('存活：ok')).toBeVisible();
  // 不接受预设数据：服务名与版本必须来自真实响应。
  await expect(page.getByText('echo-commons-server')).toBeVisible();
});

test('就绪状态按真实返回展示数据库与后台工作进程', async ({ page }) => {
  await page.goto('/app');

  await expect(page.getByText('就绪：ready')).toBeVisible();
  await expect(page.getByText('social')).toBeVisible();
  // workers 是名称到状态的映射，必须逐项列出而不是显示为对象。
  await expect(page.getByText('[object Object]')).toHaveCount(0);
});

test('管理员端运行概况与用户端分开导航', async ({ page }) => {
  await page.goto('/admin');

  await expect(page.getByText('管理员端').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: '运行状态' })).toBeVisible();

  await page.getByRole('link', { name: '用户端' }).click();
  await expect(page).toHaveURL(/\/app$/);
});

test('后端不可达时点明跨域拒绝并显示页面来源', async ({ page }) => {
  await page.route('**/health/**', (route) => route.abort());
  await page.goto('/app');

  // 存活与就绪各自独立报错，两处都应给出可读提示。
  const alerts = page.getByRole('alert');
  await expect(alerts).toHaveCount(2);

  const first = alerts.first();
  // 不能只说「无法连接」：浏览器无法区分后端未启动与被跨域拒绝，
  // 提示必须同时给出两种可能，否则会把排查方向引向错误的一侧。
  await expect(first).toContainText('无法连接后端或被跨域策略拒绝');
  await expect(first).toContainText('http://127.0.0.1:8765');
  // 页面来源必须出现在提示里，这是要写进 cors_origins 的值。
  await expect(first).toContainText('http://localhost:5173');
  await expect(page.getByRole('heading', { name: '后端连接' })).toBeVisible();
});
