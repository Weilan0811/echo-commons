import { expect, test } from '@playwright/test';

/**
 * 管理端只读查询的端到端验证。
 *
 * 管理接口没有桩服务，全部对运行中的后端执行。服务端默认只监听 127.0.0.1
 * 且没有管理员账户认证，因此这些用例只在本地开发环境有意义。
 *
 * 范围标识固定为联调时建立的那份数据：管理端按标识读取，换成时间戳会指向
 * 不存在的对象。用例验证读取与呈现，不写入任何管理数据。
 */
const communityId = 'night-diner';
const lobbyId = 'night-diner-lobby';
const characterId = 'xiaojin-main';

test('管理端从社群列表进入社群诊断', async ({ page }) => {
  await page.goto('/admin/communities');
  await expect(page.getByRole('heading', { level: 1, name: '社群' })).toBeVisible();
  await expect(page.getByText('全部社群')).toBeVisible();

  await page.getByRole('link', { name: '深夜食堂' }).click();
  await expect(page).toHaveURL(new RegExp('/admin/communities/' + communityId));
  // 区块标题带计数，用 heading 定位而不是精确文本。
  for (const section of ['角色', '会话', '任务', '成员']) {
    await expect(page.getByRole('heading', { name: new RegExp(section) })).toBeVisible();
  }
});

test('会话诊断读取消息与轮次', async ({ page }) => {
  await page.goto('/admin/communities/' + communityId + '/conversations/' + lobbyId);
  await expect(page.getByRole('heading', { level: 1, name: lobbyId })).toBeVisible();
  await expect(page.getByRole('heading', { name: /成员区间/ })).toBeVisible();
  // 真实数据里有轮次，概要列表应至少有一条。
  await expect(page.getByRole('heading', { name: /轮次/ })).toBeVisible();
});

test('角色诊断按类别读取记忆', async ({ page }) => {
  await page.goto('/admin/communities/' + communityId + '/characters/' + characterId);
  await expect(page.getByRole('heading', { level: 1, name: '小槿' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^状态/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^关系/ })).toBeVisible();

  // 记忆五类共用一个路径，切换类别不应报错。
  await page.getByRole('combobox').first().selectOption('entries');
  await expect(page.getByRole('heading', { name: /^记忆/ })).toBeVisible();
});

test('管理端玩家列表包含所有玩家', async ({ page }) => {
  await page.goto('/admin/players');
  await expect(page.getByRole('heading', { level: 1, name: '玩家' })).toBeVisible();
  await expect(page.getByText('阿澈')).toBeVisible();
  await expect(page.getByText('林舟')).toBeVisible();
});