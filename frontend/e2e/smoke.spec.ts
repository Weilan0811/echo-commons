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

test('后端不可达时给出归一后的错误而不是空白', async ({ page }) => {
  await page.route('**/health/**', (route) => route.abort());
  await page.goto('/app');

  // 存活与就绪各自独立报错，两处都应给出可读提示。
  const alerts = page.getByRole('alert');
  await expect(alerts).toHaveCount(2);
  await expect(alerts.first()).toContainText('无法连接后端');
  await expect(page.getByRole('heading', { name: '后端连接' })).toBeVisible();
});
