import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
let playerId: string;

async function create(request: APIRequestContext, name: string, owner = playerId) {
  const communityId = `u04-${randomUUID()}`;
  const response = await request.post(`${apiBase}/api/communities`, { data: {
    player_id: owner, community_id: communityId, name, timezone: 'Asia/Shanghai',
  } });
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

async function saved(request: APIRequestContext, id: string) {
  const response = await request.get(`${apiBase}/api/communities/${id}`, { params: { player_id: playerId } });
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

async function subject(page: Page, communityId: string | null = null) {
  await page.addInitScript(value => localStorage.setItem('echo-commons.subject.v1', JSON.stringify(value)), {
    playerId, playerDisplayName: '社群页面验证', communityId, communityName: '',
  });
}

test.beforeEach(async ({ request, page }) => {
  playerId = `u04-${randomUUID()}`;
  const response = await request.post(`${apiBase}/api/players`, { data: { player_id: playerId, display_name: '社群页面验证' } });
  expect(response.status()).toBe(201);
  await subject(page);
});

test('空列表、邀请展开、真实加入失败保留输入与加入成功', async ({ page, request }) => {
  await page.goto('/app/communities');
  await expect(page.getByText('还没有常去的地方。', { exact: false })).toBeVisible();
  await expect(page.getByLabel('社群标识')).toHaveCount(0);
  await page.getByRole('button', { name: /前往朋友的世界/ }).click();
  await page.getByLabel('社群标识').fill('missing-u04-world');
  await page.getByLabel('社群标识').press('Enter');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('社群标识')).toHaveValue('missing-u04-world');
  await expect(page.getByRole('alert')).not.toContainText('NotFoundError');
  const other = `other-${randomUUID()}`;
  await request.post(`${apiBase}/api/players`, { data: { player_id: other, display_name: '朋友' } });
  const world = await create(request, '朋友的世界', other);
  await page.getByLabel('社群标识').fill(world.community_id);
  await page.getByRole('button', { name: '加入社群', exact: true }).click();
  await expect(page.getByRole('button', { name: '进入朋友的世界', exact: true })).toBeVisible();
  await expect(page.getByLabel('社群标识')).toHaveCount(0);
  expect((await saved(request, world.community_id)).status).toBe('paused');
});

test('两个场景卡、键盘详情与返回焦点、刷新和进入操作', async ({ page, request }) => {
  const first = await create(request, '深夜食堂');
  const second = await create(request, '湖畔小镇');
  await subject(page, first.community_id);
  await page.goto('/app/communities');
  await expect(page.getByRole('button', { name: '进入深夜食堂', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '进入湖畔小镇', exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('community-list.png'), animations: 'disabled' });
  await expect(page.getByRole('button', { name: '暂停社群', exact: true })).toHaveCount(0);
  const details = page.getByRole('button', { name: '湖畔小镇的社群详情', exact: true });
  await details.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(new RegExp(`/app/communities/${second.community_id}$`));
  await expect(page.getByRole('heading', { name: '湖畔小镇', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '启动社群', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '返回社群列表' }).click();
  await expect(details).toBeFocused();
  await details.press('Enter');
  await page.goBack();
  await expect(details).toBeFocused();
  await page.getByRole('button', { name: '进入湖畔小镇', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/chat$/);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('echo-commons.subject.v1')!).communityId)).toBe(second.community_id);
  expect((await saved(request, second.community_id)).status).toBe('paused');
});

test('封面预览、放弃、键盘保存和连续状态修改使用新版本', async ({ page, request }) => {
  const world = await create(request, '校园晚风');
  await page.goto(`/app/communities/${world.community_id}`);
  const versions: number[] = [];
  page.on('request', outgoing => {
    if (outgoing.method() === 'PATCH' && outgoing.url().includes(`/communities/${world.community_id}/`)) {
      versions.push(outgoing.postDataJSON().expected_version);
    }
  });
  await page.getByRole('button', { name: '选择深夜食堂', exact: true }).click();
  await expect(page.getByRole('img', { name: '校园晚风封面预览' })).toHaveAttribute('src', '/assets/covers/diner.webp');
  expect((await saved(request, world.community_id)).cover_ref).toBeNull();
  await page.getByRole('button', { name: '放弃编辑' }).click();
  await expect(page.getByRole('img', { name: '校园晚风封面预览' })).toHaveCount(0);
  await page.getByRole('button', { name: '选择深夜食堂', exact: true }).click();
  await page.getByRole('button', { name: '保存封面', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: '保存封面', exact: true })).toHaveCount(0);
  await expect.poll(async () => (await saved(request, world.community_id)).cover_ref).toBe('diner');
  await page.screenshot({ path: test.info().outputPath('community-cover.png'), animations: 'disabled' });
  await page.getByRole('button', { name: '启动社群', exact: true }).click();
  await expect(page.getByRole('button', { name: '暂停社群', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '暂停社群', exact: true }).click();
  await expect(page.getByRole('button', { name: '启动社群', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '选择默认渐变', exact: true }).click();
  await page.getByRole('button', { name: '保存封面', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存封面', exact: true })).toHaveCount(0);
  const actual = await saved(request, world.community_id);
  expect(actual.cover_ref).toBeNull();
  expect(actual.status).toBe('paused');
  expect(actual.state_version).toBe(4);
  expect(versions).toEqual([0, 1, 2, 3]);
  await page.reload();
  await expect(page.getByRole('button', { name: '选择默认渐变', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: test.info().outputPath('community-detail.png'), animations: 'disabled' });
});

test('创建默认本地时区、重复标识失败保留资料、创建后暂停与窄屏固定操作', async ({ page, request }) => {
  const existing = await create(request, '已有世界');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/app/communities');
  await page.getByRole('button', { name: /开辟新天地/ }).click();
  await expect(page).toHaveURL(/\/app\/communities\/new$/);
  const localZone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  await expect(page.getByLabel('世界时区')).toHaveValue(localZone);
  await page.getByLabel('社群名称').fill('新建湖畔');
  for (const label of ['社群名称', '世界时区']) {
    const field = await page.getByLabel(label).boundingBox();
    expect(field!.x + field!.width).toBeLessThanOrEqual(359);
  }
  await page.getByRole('button', { name: '选择湖', exact: true }).click();
  await page.getByText('详细选项', { exact: true }).click();
  await page.getByLabel('社群标识').fill(existing.community_id);
  await page.getByRole('button', { name: '创建社群', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('这个社群标识已经被使用');
  await expect(page.getByRole('alert')).toBeInViewport();
  await expect(page.getByLabel('社群名称')).toHaveValue('新建湖畔');
  await expect(page.getByLabel('社群标识')).toHaveValue(existing.community_id);
  await expect(page.getByRole('button', { name: '选择湖', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: test.info().outputPath('community-create.png'), animations: 'disabled' });
  const newId = `u04-${randomUUID()}`;
  await page.getByLabel('社群标识').fill(newId);
  await page.getByRole('button', { name: '创建社群', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/communities/${newId}$`));
  await expect(page.getByRole('button', { name: '启动社群', exact: true })).toBeVisible();
  expect((await saved(request, newId)).timezone).toBe(localZone);
  expect((await saved(request, newId)).cover_ref).toBe('lakeside');
  await page.getByRole('button', { name: '选择深夜食堂', exact: true }).click();
  const bounds = await page.getByRole('button', { name: '保存封面', exact: true }).boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath('community-mobile.png'), animations: 'disabled' });
  await page.getByRole('button', { name: '放弃编辑' }).click();
  await page.getByRole('button', { name: '返回社群列表' }).click();
  await expect(page.getByRole('button', { name: /开辟新天地/ })).toBeFocused();
});

test('已有资产封面保留至主动保存，非成员详情返回友好提示', async ({ page, request }) => {
  const world = await create(request, '资产封面世界');
  const uploaded = await request.post(`${apiBase}/api/assets/images`, { multipart: {
    player_id: playerId, purpose: 'community_cover',
    file: { name: 'cover.png', mimeType: 'image/png', buffer: await readFile('public/assets/characters/xiaojin/illustration.png') },
  } });
  expect(uploaded.ok(), await uploaded.text()).toBe(true);
  const asset = await uploaded.json();
  const changed = await request.patch(`${apiBase}/api/communities/${world.community_id}/appearance`, { data: {
    player_id: playerId, expected_version: 0, cover_kind: 'asset', cover_ref: asset.asset_id,
  } });
  expect(changed.ok(), await changed.text()).toBe(true);
  await page.goto(`/app/communities/${world.community_id}`);
  await expect(page.getByRole('img', { name: '资产封面世界封面预览' })).toHaveAttribute('src', new RegExp(asset.asset_id));
  await expect(page.getByRole('button', { name: '选择默认渐变', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: '选择深夜食堂', exact: true }).click();
  await page.getByRole('button', { name: '放弃编辑' }).click();
  expect((await saved(request, world.community_id)).cover_ref).toBe(asset.asset_id);
  await expect(page.getByRole('img', { name: '资产封面世界封面预览' })).toHaveAttribute('src', new RegExp(asset.asset_id));
  const other = `other-${randomUUID()}`;
  await request.post(`${apiBase}/api/players`, { data: { player_id: other, display_name: '其他玩家' } });
  const privateWorld = await create(request, '未加入的世界', other);
  await page.goto(`/app/communities/${privateWorld.community_id}`);
  await expect(page.getByRole('alert')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('alert')).not.toContainText('NotFoundError');
  await expect(page.getByRole('button', { name: '启动社群', exact: true })).toHaveCount(0);
});

test('没有登记身份时关闭创建与加入入口', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('echo-commons.subject.v1'));
  await page.goto('/app/communities');
  await expect(page.getByText('先登记身份，才能查看已加入的社群。')).toBeVisible();
  await expect(page.getByRole('button', { name: /开辟新天地/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: /前往朋友的世界/ })).toBeDisabled();
});

test('实际版本冲突保留封面选择，刷新权威版本后可以保存', async ({ page, request }) => {
  const world = await create(request, '版本检查世界');
  await page.goto(`/app/communities/${world.community_id}`);
  await page.getByRole('button', { name: '选择深夜食堂', exact: true }).click();
  const external = await request.patch(`${apiBase}/api/communities/${world.community_id}/status`, { data: {
    player_id: playerId, expected_version: 0, status: 'active',
  } });
  expect(external.ok(), await external.text()).toBe(true);
  // 详情未成为当前社群，实际外部修改不会提前更新此处缓存。
  const failed = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith('/appearance'));
  await page.getByRole('button', { name: '保存封面', exact: true }).click();
  expect((await failed).status()).toBe(409);
  await expect(page.getByRole('alert')).toContainText('社群信息刚刚更新');
  await expect(page.getByRole('alert')).toBeInViewport();
  await expect(page.getByRole('button', { name: '选择深夜食堂', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '暂停社群', exact: true })).toBeEnabled();
  expect((await saved(request, world.community_id)).cover_ref).toBeNull();
  await page.getByRole('button', { name: '保存封面', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存封面', exact: true })).toHaveCount(0);
  expect((await saved(request, world.community_id)).state_version).toBe(2);
  expect((await saved(request, world.community_id)).cover_ref).toBe('diner');
});
