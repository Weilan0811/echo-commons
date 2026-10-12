import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';

async function createWorld(request: APIRequestContext) {
  const communityId = randomUUID();
  const alice = randomUUID();
  const bob = randomUUID();
  async function write(path: string, data: unknown, method = 'POST') {
    const response = await request.fetch(`${apiBase}${path}`, { method, data });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  }
  await write('/api/players', { player_id: alice, display_name: '创建玩家' });
  await write('/api/players', { player_id: bob, display_name: '同伴玩家' });
  await write('/api/communities', { player_id: alice, community_id: communityId, name: '会话验证', timezone: 'UTC' });
  await write(`/api/communities/${communityId}/players/${bob}`, {}, 'PUT');
  await write(`/api/communities/${communityId}/status`, { player_id: alice, status: 'active', expected_version: 0 }, 'PATCH');
  const first = await write(`/api/communities/${communityId}/characters`, { player_id: alice, blueprint_id: 'xiaojin', memory_mode: 'simple' });
  const second = await write(`/api/communities/${communityId}/characters`, { player_id: alice, blueprint_id: 'xiaojin', memory_mode: 'simple' });
  const subject = { playerId: alice, playerDisplayName: '创建玩家', communityId, communityName: '会话验证' };
  return { alice, bob, first: first.character_id, second: second.character_id, subject, write };
}

async function identify(page: Page, subject: object) {
  await page.addInitScript((value) => localStorage.setItem('echo-commons.subject.v1', JSON.stringify(value)), subject);
}

async function details(page: Page) {
  await page.getByRole('button', { name: '会话详情', exact: true }).click();
  return page.getByRole('dialog');
}

test('群聊：人数、隐藏、找回、退出区间、重新加入与多人结束通知', async ({ page, request, browser }) => {
  const world = await createWorld(request);
  await identify(page, world.subject);
  await page.goto('/app/chat');
  await page.getByRole('button', { name: '新建', exact: true }).click();
  await page.getByRole('button', { name: /小槿.*角色/ }).first().click();
  await expect(page.getByRole('button', { name: '创建', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: /同伴玩家.*玩家/ }).click();
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/chat\/[^/?]+$/);
  const conversation = new URL(page.url()).pathname.split('/').at(-1)!;
  await expect(page.getByRole('textbox')).toBeVisible();
  await world.write(`/api/conversations/${conversation}/messages`, { player_id: world.bob, client_message_id: randomUUID(), text: '退出之前的消息' });
  await expect(page.getByText('退出之前的消息', { exact: true }).first()).toBeVisible();
  let dialog = await details(page);
  await expect(dialog.getByText('创建者：创建玩家')).toBeVisible();
  const operationIds: string[] = [];
  page.on('request', (value) => {
    if (value.method() === 'PUT' && value.url().endsWith('/list-preference')) {
      operationIds.push(value.postDataJSON().client_operation_id);
    }
  });
  await page.context().setOffline(true);
  await dialog.getByRole('button', { name: '从我的列表移除', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '从我的列表移除', exact: true })).toBeEnabled();
  await page.context().setOffline(false);
  await dialog.getByRole('button', { name: '从我的列表移除', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '找回会话', exact: true })).toBeVisible();
  expect(operationIds).toHaveLength(2);
  expect(operationIds[0]).toBe(operationIds[1]);
  await dialog.getByRole('button', { name: '关闭会话详情' }).click();
  await page.getByRole('button', { name: '隐藏', exact: true }).click();
  await expect(page.getByRole('button', { name: /小槿.*同伴玩家|同伴玩家.*小槿/ }).first()).toBeVisible();
  dialog = await details(page);
  await dialog.getByRole('button', { name: '找回会话', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '从我的列表移除', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: '../server/data/verification/u08-details-1440.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../server/data/verification/u08-details-390.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await dialog.getByRole('button', { name: '退出群聊', exact: true }).click();
  await dialog.getByRole('button', { name: '确认退出', exact: true }).click();
  await expect(page.locator('textarea')).toHaveCount(0);
  await world.write(`/api/conversations/${conversation}/messages`, { player_id: world.bob, client_message_id: randomUUID(), text: '退出期间不可见的消息' });
  await dialog.getByRole('button', { name: '重新加入', exact: true }).click();
  await dialog.getByRole('button', { name: '关闭会话详情' }).click();
  await expect(page.getByRole('textbox')).toBeVisible();
  await expect(page.getByText('退出之前的消息', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('退出期间不可见的消息', { exact: true })).toHaveCount(0);
  const peerContext = await browser.newContext();
  try {
    const peer = await peerContext.newPage();
    await identify(peer, { ...world.subject, playerId: world.bob, playerDisplayName: '同伴玩家' });
    await peer.goto(`/app/chat/${conversation}`);
    await expect(peer.getByRole('textbox')).toBeVisible();
    const peerDialog = await details(peer);
    await expect(peerDialog.getByRole('button', { name: '结束群聊', exact: true })).toHaveCount(0);
    await peerDialog.getByRole('button', { name: '关闭会话详情' }).click();
    dialog = await details(page);
    await dialog.getByRole('button', { name: '结束群聊', exact: true }).click();
    await dialog.getByRole('button', { name: '确认结束', exact: true }).click();
    await expect(dialog.getByText(/已经结束/)).toBeVisible();
    await expect(peer.getByRole('textbox')).toHaveCount(0);
    await expect(peer.getByText('退出期间不可见的消息', { exact: true }).first()).toBeVisible();
    await dialog.getByRole('button', { name: '关闭会话详情' }).click();
    await page.getByRole('button', { name: '已结束', exact: true }).click();
    await expect(page.getByRole('button', { name: /小槿.*同伴玩家|同伴玩家.*小槿/ }).first()).toBeVisible();
  } finally {
    await peerContext.close();
  }
});

test('最后一名玩家退出后，群聊自动结束且历史可读', async ({ page, request }) => {
  const world = await createWorld(request);
  await identify(page, world.subject);
  await page.goto('/app/chat');
  await page.getByRole('button', { name: '新建', exact: true }).click();
  await expect(page.getByRole('button', { name: /小槿.*角色/ })).toHaveCount(2);
  for (const button of await page.getByRole('button', { name: /小槿.*角色/ }).all()) await button.click();
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await expect(page.getByRole('textbox')).toBeVisible();
  const dialog = await details(page);
  await dialog.getByRole('button', { name: '退出群聊', exact: true }).click();
  await dialog.getByRole('button', { name: '确认退出', exact: true }).click();
  await expect(dialog.getByText(/已经结束/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: '重新加入', exact: true })).toHaveCount(0);
  await expect(page.locator('textarea')).toHaveCount(0);
});

test('私聊重复打开、退出再打开保持相同会话并恢复个人列表', async ({ page, request }) => {
  const world = await createWorld(request);
  await identify(page, world.subject);
  await page.goto('/app/chat');
  async function open() {
    await page.getByRole('button', { name: '新建', exact: true }).click();
    await page.getByRole('button', { name: '私聊', exact: true }).click();
    await page.getByRole('button', { name: /小槿.*角色/ }).first().click();
    await page.getByRole('button', { name: '打开私聊', exact: true }).click();
    await expect(page.getByRole('textbox')).toBeVisible();
    return new URL(page.url()).pathname;
  }
  const original = await open();
  expect(await open()).toBe(original);
  const dialog = await details(page);
  await dialog.getByRole('button', { name: '从我的列表移除', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '找回会话', exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '退出私聊', exact: true }).click();
  await dialog.getByRole('button', { name: '确认退出', exact: true }).click();
  await expect(page.locator('textarea')).toHaveCount(0);
  await dialog.getByRole('button', { name: '关闭会话详情' }).click();
  await page.getByRole('button', { name: '隐藏', exact: true }).click();
  await expect(page.getByRole('button', { name: /小槿/ }).first()).toBeVisible();
  expect(await open()).toBe(original);
  const restored = await details(page);
  await expect(restored.getByRole('button', { name: '从我的列表移除', exact: true })).toBeVisible();
});

test('会话列表使用实际游标读取下一页，筛选各自保留范围', async ({ page, request }) => {
  const world = await createWorld(request);
  for (let index = 0; index < 51; index++) {
    await world.write(`/api/communities/${world.subject.communityId}/conversations`, {
      player_id: world.alice, kind: 'group', actors: [
        { kind: 'player', actor_id: world.alice },
        { kind: 'character', actor_id: world.first },
        { kind: 'character', actor_id: world.second },
      ],
    });
  }
  await identify(page, world.subject);
  const firstPage = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/conversations' && !url.searchParams.has('cursor') && response.ok();
  });
  await page.goto('/app/chat');
  const cursor = (await (await firstPage).json()).cursor;
  await expect(page.getByRole('button', { name: /小槿、小槿/ })).toHaveCount(50);
  const nextPage = page.waitForResponse((response) => new URL(response.url()).searchParams.get('cursor') === cursor && response.ok());
  await page.getByRole('button', { name: '加载更多会话', exact: true }).click();
  expect((await (await nextPage).json()).items).toHaveLength(1);
  await expect(page.getByRole('button', { name: /小槿、小槿/ })).toHaveCount(51);
  await expect(page.getByRole('button', { name: '加载更多会话', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '隐藏', exact: true }).click();
  await expect(page.getByRole('button', { name: /小槿、小槿/ })).toHaveCount(0);
});
