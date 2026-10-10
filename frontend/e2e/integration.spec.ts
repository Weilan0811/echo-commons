import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
const playerId = `integration-${randomUUID()}`;
const communityId = `integration-${randomUUID()}`;
let illustration: { asset_id: string };
async function post(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(`${apiBase}${path}`, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}
test.beforeAll(async ({ request }) => {
  await post(request, '/api/players', { player_id: playerId, display_name: '能力验证玩家' });
  await post(request, '/api/communities', { player_id: playerId, community_id: communityId, name: '能力验证社群', timezone: 'UTC' });
  const uploaded = await request.post(`${apiBase}/api/assets/images`, { multipart: {
    player_id: playerId, purpose: 'character_illustration',
    file: { name: 'illustration.png', mimeType: 'image/png', buffer: await readFile('public/assets/characters/xiaojin/illustration.png') },
  } });
  expect(uploaded.ok(), await uploaded.text()).toBe(true);
  illustration = await uploaded.json();
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript((subject) => localStorage.setItem('echo-commons.subject.v1', JSON.stringify(subject)), {
    playerId, playerDisplayName: '能力验证玩家', communityId, communityName: '能力验证社群',
  });
});

test('角色选择真实插画、裁剪头像并恢复默认外观', async ({ request, page }) => {
  const character = await post(request, `/api/communities/${communityId}/characters`, { player_id: playerId, blueprint_id: 'xiaojin', memory_mode: 'simple' });
  await page.goto('/app/characters');
  await page.getByRole('button', { name: /小槿.*可参与对话/ }).click();
  await page.getByRole('button', { name: '更换插画与头像' }).click();
  const picker = page.getByRole('dialog', { name: '角色插画与头像' });
  await expect(picker.getByText('已有插画')).toBeVisible();
  await picker.getByRole('button', { name: '生成角色插画', exact: true }).click();
  await expect(picker.getByRole('alert')).toBeVisible();
  await expect(picker.getByRole('alert')).not.toContainText('credential');
  await expect(picker.getByRole('alert')).not.toContainText('image_model');
  await picker.getByRole('button', { name: '选择插画' }).first().click();
  await expect(picker.getByRole('alert')).toHaveCount(0);
  await expect(picker.getByRole('button', { name: '保存插画与头像' })).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('illustration-crop.png'), animations: 'disabled' });
  await picker.getByRole('button', { name: '保存插画与头像' }).click();
  await expect(picker).toHaveCount(0);
  await expect(page.getByRole('button', { name: '恢复默认外观' })).toBeVisible();
  const response = await request.get(`${apiBase}/api/communities/${communityId}/characters`, { params: { player_id: playerId } });
  const actual = (await response.json()).find((item: { character_id: string }) => item.character_id === character.character_id);
  expect(actual.avatar_asset_id).toBeTruthy();
  expect(actual.illustration_url).toContain(illustration.asset_id);
  const avatar = await request.get(`${apiBase}/api/assets/${actual.avatar_asset_id}`, { params: { player_id: playerId } });
  const image = (await avatar.json()).images.find((item: { variant: string }) => item.variant === 'standard');
  expect(image.width).toBe(image.height);
  expect(image.width).toBe(512);
  await page.getByRole('button', { name: '恢复默认外观' }).click();
  await expect(page.getByRole('button', { name: '恢复默认外观' })).toHaveCount(0);
});

test('社群启停、封面保存、管理搜索与确认清理', async ({ request, page }) => {
  const id = `cleanup-${randomUUID()}`;
  await post(request, '/api/communities', { player_id: playerId, community_id: id, name: '清理验证社群', timezone: 'UTC' });
  await page.addInitScript((community) => {
    const subject = JSON.parse(localStorage.getItem('echo-commons.subject.v1')!);
    localStorage.setItem('echo-commons.subject.v1', JSON.stringify({ ...subject, communityId: community }));
  }, id);
  await page.goto('/app/communities');
  await page.getByRole('button', { name: '启动社群', exact: true }).click();
  await expect(page.getByRole('button', { name: '暂停社群', exact: true })).toBeVisible();
  await page.getByLabel('官方封面', { exact: true }).selectOption('diner');
  await expect.poll(async () => {
    const response = await request.get(`${apiBase}/api/communities/${id}`, { params: { player_id: playerId } });
    return (await response.json()).cover_ref;
  }).toBe('diner');
  await page.getByRole('button', { name: '暂停社群', exact: true }).click();
  await expect(page.getByRole('button', { name: '启动社群', exact: true })).toBeVisible();
  await page.goto('/admin/communities');
  await page.getByPlaceholder('输入名称或编号，例如 wide-test').fill(id);
  await expect(page.getByRole('link', { name: '清理验证社群', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '清理验证社群', exact: true }).click();
  await page.getByRole('button', { name: '预览清理范围' }).click();
  await expect(page.getByRole('button', { name: '确认删除社群' })).toBeDisabled();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '确认删除社群' }).click();
  await expect(page).toHaveURL(/\/admin\/communities$/);
  expect((await request.get(`${apiBase}/api/communities/${id}`, { params: { player_id: playerId } })).status()).toBe(404);
  expect((await request.get(`${apiBase}/api/players/${playerId}`)).ok()).toBe(true);
});

test('草稿保存裁剪外观并在刷新后保留', async ({ request, page }) => {
  const draft = await post(request, '/api/character-drafts', {
    player_id: playerId, draft_id: randomUUID(), display_name: '插画草稿', description: '图像保存验证角色',
    story: '', interview: [], avatar_url: null,
  });
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);
  await page.getByRole('button', { name: '选择或生成角色插画' }).click();
  const picker = page.getByRole('dialog', { name: '角色插画与头像' });
  await picker.getByRole('button', { name: '选择插画' }).first().click();
  await expect(picker.getByRole('button', { name: '保存插画与头像' })).toBeEnabled();
  await picker.getByRole('button', { name: '保存插画与头像' }).click();
  await expect(picker).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('img', { name: '已选择的头像' })).toBeVisible();
  const response = await request.get(`${apiBase}/api/character-drafts/${draft.draft_id}`, { params: { player_id: playerId } });
  const saved = await response.json();
  expect(saved.content.avatar_asset_id).toBeTruthy();
  expect(saved.content.avatar_url).toBeNull();
});

test('实时消息顺序、共享连接、断网恢复与空闲时停止消息轮询', async ({ page, context, request }) => {
  const conversation = await post(request, `/api/communities/${communityId}/conversations`, {
    player_id: playerId, kind: 'group', actors: [{ kind: 'player', actor_id: playerId }],
  });
  const id = conversation.conversation_id;
  const outgoing: string[] = [];
  page.on('request', (request) => { if (request.method() === 'GET') outgoing.push(new URL(request.url()).pathname); });
  await page.goto(`/app/chat/${id}`);
  await expect(page.getByPlaceholder('说点什么…')).toBeVisible();
  await expect.poll(() => outgoing.filter((path) => path === `/api/communities/${communityId}/events`).length).toBe(1);
  expect(outgoing.indexOf(`/api/communities/${communityId}/events/cursor`)).toBeLessThan(outgoing.indexOf(`/api/conversations/${id}/messages/history`));
  expect(outgoing.indexOf(`/api/conversations/${id}/messages/history`)).toBeLessThan(outgoing.indexOf(`/api/communities/${communityId}/events`));
  const before = outgoing.filter((path) => path === `/api/conversations/${id}/messages`).length;
  await page.waitForTimeout(8500);
  expect(outgoing.filter((path) => path === `/api/conversations/${id}/messages`).length).toBe(before);
  await post(request, `/api/conversations/${id}/messages`, { player_id: playerId, client_message_id: randomUUID(), text: '实时到达验证' });
  await expect(page.getByRole('main').getByText('实时到达验证', { exact: true })).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByRole('status')).toContainText('连接恢复中');
  await post(request, `/api/conversations/${id}/messages`, { player_id: playerId, client_message_id: randomUUID(), text: '断网期间的新消息' });
  await context.setOffline(false);
  await expect(page.getByRole('main').getByText('断网期间的新消息', { exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('main').getByText('实时到达验证', { exact: true })).toHaveCount(1);
});
