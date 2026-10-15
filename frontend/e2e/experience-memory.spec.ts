import { expect, test } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8877';
const scope = '/internal/communities/community/characters/first';

test('真实跨场景记忆在管理详情显示时间、场景与独立覆盖', async ({ page, request }) => {
  test.skip(process.env.E2E_EXPERIENCE_HISTORY !== '1', '使用 U09 真实模型验收数据库副本');
  const response = await request.get(`${apiBase}${scope}/memory/segments`);
  expect(response.ok(), await response.text()).toBe(true);
  const segment = (await response.json()).items.find((item: { scenes: unknown[] }) => item.scenes.length === 2);
  expect(segment).toBeDefined();
  await page.goto('/admin/communities/community/characters/first');
  await page.getByRole('combobox').first().selectOption('segments');
  await page.locator('summary').filter({ hasText: segment.segment_id }).click();
  await expect(page.getByText('经历段顺序', { exact: true })).toBeVisible();
  await expect(page.getByText('经历时间', { exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '交流场景', exact: true })).toBeVisible();
  await expect(page.getByText('没有只读前情。', { exact: true })).toBeVisible();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.getByText('经历时间', { exact: true })).toBeVisible();
    const size = await page.evaluate(() => ({ viewport: window.innerWidth, document: document.documentElement.scrollWidth }));
    expect(size.document).toBeLessThanOrEqual(size.viewport);
    await page.screenshot({ path: `../server/data/verification/u09-browser/segment-${width}.png`, fullPage: true });
  }
  await page.getByRole('combobox').first().selectOption('digests');
  await page.locator('summary').filter({ hasText: '覆盖' }).first().click();
  await expect(page.getByText('已覆盖经历段', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../server/data/verification/u09-browser/digest.png', fullPage: true });
});
