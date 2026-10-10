import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

/**
 * 管理端只读查询的端到端验证。
 *
 * 管理接口没有桩服务，全部对运行中的后端执行。服务端默认只监听 127.0.0.1
 * 且没有管理员账户认证，因此这些用例只在本地开发环境有意义。
 *
 * 前置对象通过公开接口建立，管理页面只读查询，不依赖已有本地数据。
 */
const suffix = randomUUID();
const communityId = `admin-${suffix}`;
const lobbyId = `admin-lobby-${suffix}`;
const characterId = `admin-character-${suffix}`;
const communityName = `管理验证社群 ${suffix}`;
const firstName = `管理玩家甲 ${suffix}`;
const secondName = `管理玩家乙 ${suffix}`;
const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';

test.beforeAll(async ({ request }) => {
  const playerId = `admin-player-${suffix}`;
  const peerId = `admin-peer-${suffix}`;
  for (const [id, name] of [[playerId, firstName], [peerId, secondName]]) {
    const response = await request.post(`${apiBase}/api/players`, { data: { player_id: id, display_name: name } });
    expect(response.ok(), await response.text()).toBe(true);
  }
  const community = await request.post(`${apiBase}/api/communities`, {
    data: { player_id: playerId, community_id: communityId, name: communityName, timezone: 'UTC' },
  });
  expect(community.ok(), await community.text()).toBe(true);
  const character = await request.post(`${apiBase}/api/communities/${communityId}/characters`, {
    data: { player_id: playerId, character_id: characterId, blueprint_id: 'xiaojin', memory_mode: 'simple' },
  });
  expect(character.ok(), await character.text()).toBe(true);
  const conversation = await request.post(`${apiBase}/api/communities/${communityId}/conversations`, {
    data: { player_id: playerId, conversation_id: lobbyId, kind: 'direct', actors: [
      { kind: 'player', actor_id: playerId }, { kind: 'character', actor_id: characterId },
    ] },
  });
  expect(conversation.ok(), await conversation.text()).toBe(true);
});

test('管理端从社群列表进入社群诊断', async ({ page }) => {
  await page.goto('/admin/communities');
  await expect(page.getByRole('heading', { level: 1, name: '社群' })).toBeVisible();
  await expect(page.getByText('全部社群')).toBeVisible();

  // 开发库社群累积后，新建社群可能在后续分页（后端单次上限 200）。
  const communityLink = page.getByRole('link', { name: communityName });
  const moreCommunities = page.getByRole('button', { name: '读取更多' });
  for (let pageIndex = 0; pageIndex < 9 && (await communityLink.count()) === 0; pageIndex += 1) {
    const response = page.waitForResponse((value) => value.url().includes('/internal/communities?'));
    await moreCommunities.click();
    await response;
  }

  await communityLink.click();
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
  await expect(page.getByRole('heading', { name: /轮次/ })).toBeVisible();
});

test('角色诊断按类别读取记忆', async ({ page }) => {
  await page.goto('/admin/communities/' + communityId + '/characters/' + characterId);
  await expect(page.getByRole('heading', { level: 1, name: '小槿' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^状态/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^关系/ })).toBeVisible();

  // 记忆五类共用一个路径，切换类别不应报错。
  await page.getByRole('combobox').first().selectOption('entries');
  await expect(page.getByRole('heading', { name: /^记忆\d/ })).toBeVisible();
});

test('管理端玩家列表包含所有玩家', async ({ page }) => {
  await page.goto('/admin/players');
  await expect(page.getByRole('heading', { level: 1, name: '玩家' })).toBeVisible();

  // 开发库里玩家会不断累积，新玩家可能在后续分页，逐页读取直到全部出现。
  // 后端单次上限 200，因此最多再点 9 次；每次等列表响应完成再继续，避免连点越过响应。
  const required = [firstName, secondName];
  const more = page.getByRole('button', { name: '读取更多' });
  for (let pageIndex = 0; pageIndex < 9; pageIndex += 1) {
    if (required.every((name) => page.getByText(name, { exact: true }).count() > 0)) break;
    const response = page.waitForResponse((value) => value.url().includes('/internal/players?'));
    await more.click();
    await response;
  }
  await expect(page.getByText(firstName, { exact: true })).toBeVisible();
  await expect(page.getByText(secondName, { exact: true })).toBeVisible();
});

test('反思状态筛选使用后端支持的全部状态', async ({ page }) => {
  await page.goto('/admin/communities/' + communityId + '/characters/' + characterId);
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: /^反思/ }) });
  const select = section.getByRole('combobox');
  const statuses = ['pending', 'running', 'retry_wait', 'completed', 'partial', 'failed', 'cancelled'];
  await expect(select.locator('option')).toHaveText(['全部状态', ...statuses]);
  for (const status of statuses) {
    const response = page.waitForResponse((response) =>
      response.url().includes('/reflection/runs?') && response.url().includes('status=' + status),
    );
    await select.selectOption(status);
    expect((await response).status()).toBe(200);
    await expect(section.getByText('没有反思运行。')).toBeVisible();
  }
});
