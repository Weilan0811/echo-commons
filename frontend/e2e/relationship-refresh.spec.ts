import { expect, test } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
const xiaoli = 'e4477e61-9989-4871-964d-103e6206a9ac';

test('真实历史关系：自然称呼、离线重试和单个目标刷新', async ({ page, request }) => {
  test.skip(process.env.E2E_RELATIONSHIP_HISTORY !== '1', '需要真实历史数据库副本');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/admin/communities/night-diner/characters/${xiaoli}`);
  const relation = page.locator('details').filter({ has: page.locator('summary').filter({ hasText: '小槿' }) }).first();
  await relation.locator('summary').first().click();
  await expect(relation.getByText('态度概述', { exact: true })).toBeVisible();
  const requests: string[] = [];
  page.on('request', (value) => {
    if (value.method() === 'POST' && value.url().includes('/reflection/relationship-attitudes')) {
      requests.push(value.postDataJSON().request_id);
    }
  });
  await page.context().setOffline(true);
  await relation.getByRole('button', { name: '重新整理关系描述', exact: true }).click();
  await expect(relation.getByRole('button', { name: '重试整理', exact: true })).toBeEnabled();
  await page.context().setOffline(false);
  await relation.getByRole('button', { name: '重试整理', exact: true }).click();
  await expect(relation.getByRole('button', { name: '正在整理…', exact: true })).toBeDisabled();
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBe(requests[1]);
  const response = await request.get(`${apiBase}/internal/communities/night-diner/characters/${xiaoli}/relationships`);
  const rows = (await response.json()).items;
  expect(rows.find((row: { target_id: string }) => row.target_id === 'xiaojin-main').attitude_refresh.request_kind).toBe('manual');
  expect(rows.find((row: { target_id: string }) => row.target_id === 'lin').attitude_refresh).toBeNull();
  await page.screenshot({ path: '../server/data/verification/u06-admin-1440.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await relation.scrollIntoViewIfNeeded();
  await expect(relation.getByRole('button', { name: '正在整理…', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../server/data/verification/u06-admin-390.png', fullPage: true });
});

test('真实历史关系：一次安排全部目标，保留旧描述与数值', async ({ page, request }) => {
  test.skip(process.env.E2E_RELATIONSHIP_HISTORY !== '1', '需要真实历史数据库副本');
  const url = `${apiBase}/internal/communities/night-diner/characters/xiaojin-main/relationships`;
  const before = (await (await request.get(url)).json()).items;
  await page.goto('/admin/communities/night-diner/characters/xiaojin-main');
  await page.getByRole('button', { name: '重新整理全部关系描述', exact: true }).click();
  await expect(page.getByRole('button', { name: '重新整理全部关系描述', exact: true })).toBeDisabled();
  const after = (await (await request.get(url)).json()).items;
  expect(after).toHaveLength(before.length);
  expect(after.every((row: { attitude_refresh: { status: string } }) => row.attitude_refresh.status === 'pending')).toBe(true);
  for (let index = 0; index < after.length; index++) {
    for (const field of ['affection', 'trust', 'attachment', 'state_version', 'attitude_summary']) {
      expect(after[index][field]).toEqual(before[index][field]);
    }
  }
});
