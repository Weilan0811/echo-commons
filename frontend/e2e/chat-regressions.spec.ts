import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
const suffix = randomUUID();
const playerId = `reading-${suffix}`;
const communityId = `reading-${suffix}`;

async function post(api: APIRequestContext, path: string, data: unknown) {
  const response = await api.post(`${apiBase}${path}`, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

async function conversation(api: APIRequestContext) {
  const result = await post(api, `/api/communities/${communityId}/conversations`, {
    player_id: playerId, kind: 'group', actors: [{ kind: 'player', actor_id: playerId }],
  });
  return result.conversation_id as string;
}

async function message(api: APIRequestContext, id: string, text: string) {
  return post(api, `/api/conversations/${id}/messages`, {
    player_id: playerId, client_message_id: randomUUID(), text,
  });
}

async function openChat(page: Page, id: string) {
  const history = page.waitForResponse((response) =>
    response.url().includes(`/conversations/${id}/messages/history`) && response.ok());
  await page.goto(`/app/chat/${id}`);
  await history;
  await expect(page.getByPlaceholder('说点什么…')).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  await post(request, '/api/players', { player_id: playerId, display_name: '读取验证玩家' });
  await post(request, '/api/communities', {
    player_id: playerId, community_id: communityId, name: '读取验证社群', timezone: 'UTC',
  });
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript((subject) => {
    localStorage.setItem('echo-commons.subject.v1', JSON.stringify(subject));
  }, { playerId, playerDisplayName: '读取验证玩家', communityId, communityName: '读取验证社群' });
});

test('历史连续翻页到结束，每条消息只展示一次', async ({ page, request }) => {
  test.setTimeout(60_000);
  const id = await conversation(request);
  for (let index = 1; index <= 120; index++) await message(request, id, `历史记录-${index}-结束`);
  await openChat(page, id);
  await expect(page.getByRole('main').getByText('历史记录-120-结束', { exact: true })).toBeVisible();
  await expect(page.getByRole('main').getByText('历史记录-1-结束', { exact: true })).toHaveCount(0);
  const older = page.getByRole('button', { name: '读取更早的消息', exact: true });
  await older.click();
  await expect(page.getByRole('main').getByText('历史记录-21-结束', { exact: true })).toHaveCount(1);
  await older.click();
  await expect(page.getByRole('main').getByText('历史记录-1-结束', { exact: true })).toHaveCount(1);
  await expect(older).toHaveCount(0);
  for (let index = 1; index <= 120; index++) {
    await expect(page.getByRole('main').getByText(`历史记录-${index}-结束`, { exact: true })).toHaveCount(1);
  }
});

test('超过一页的新增消息全部读取，后续轮询继续推进并保留旧消息', async ({ page, request }) => {
  test.setTimeout(60_000);
  const id = await conversation(request);
  await openChat(page, id);
  const responses: { has_more: boolean; cursor: string }[] = [];
  page.on('response', async (response) => {
    if (response.request().method() === 'GET' && new URL(response.url()).pathname === `/api/conversations/${id}/messages`) {
      responses.push(await response.json());
    }
  });
  await Promise.all(Array.from({ length: 65 }, (_, index) => message(request, id, `新增记录-${index + 1}-结束`)));
  await expect(page.getByRole('main').getByText('新增记录-65-结束', { exact: true })).toBeVisible({ timeout: 15_000 });
  await message(request, id, '后续记录-结束');
  await expect(page.getByRole('main').getByText('后续记录-结束', { exact: true })).toBeVisible({ timeout: 10_000 });
  for (let index = 1; index <= 65; index++) {
    await expect(page.getByRole('main').getByText(`新增记录-${index}-结束`, { exact: true })).toHaveCount(1);
  }
  expect(responses.some((response) => response.has_more)).toBe(true);
  expect(new Set(responses.map((response) => response.cursor)).size).toBeGreaterThan(1);
  await expect.poll(async () => {
    const response = await request.get(`${apiBase}/api/conversations/${id}`, { params: { player_id: playerId } });
    return (await response.json()).unread_count;
  }).toBe(0);
});

test('真实断网后重试复用编号，修改内容后使用新编号', async ({ page, context, request }) => {
  const id = await conversation(request);
  await openChat(page, id);
  const attempts: { client_message_id: string; text: string }[] = [];
  page.on('request', (outgoing) => {
    if (outgoing.method() === 'POST' && outgoing.url().endsWith(`/conversations/${id}/messages`)) {
      attempts.push(outgoing.postDataJSON());
    }
  });
  const input = page.getByPlaceholder('说点什么…');
  const send = page.getByRole('button', { name: '发送', exact: true });
  await input.fill('断网后继续发送');
  await context.setOffline(true);
  await send.click();
  await expect(page.getByRole('alert').first()).toContainText('无法连接后端');
  await expect(input).toHaveValue('断网后继续发送');
  await context.setOffline(false);
  await send.click();
  await expect(input).toHaveValue('');
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);

  await input.fill('另一条发送');
  await context.setOffline(true);
  await send.click();
  await expect(page.getByRole('alert').first()).toContainText('无法连接后端');
  await input.fill('修改后的发送');
  await context.setOffline(false);
  await send.click();
  await expect(input).toHaveValue('');
  expect(attempts).toHaveLength(4);
  expect(attempts[3]!.client_message_id).not.toBe(attempts[2]!.client_message_id);
  const history = await request.get(`${apiBase}/api/conversations/${id}/messages/history`, {
    params: { player_id: playerId },
  });
  expect((await history.json()).messages.map((item: { text: string }) => item.text))
    .toEqual(['断网后继续发送', '修改后的发送']);
});

test('模板创建使用简单模式，准备完成的角色可以选择', async ({ page, request }) => {
  await page.goto('/app/characters');
  await page.getByRole('button', { name: '从模板创建', exact: true }).click();
  const created = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith(`/communities/${communityId}/characters`));
  await page.locator('div.fixed').getByRole('button', { name: /小槿/ }).click();
  const response = await created;
  expect(response.request().postDataJSON().memory_mode).toBe('simple');
  expect((await response.json()).memory_status).toBe('ready');
  await expect(page.getByText('可参与对话', { exact: true })).toBeVisible();
  await page.goto('/app/chat');
  await page.getByRole('button', { name: '新建', exact: true }).click();
  await expect(page.locator('div.fixed').getByRole('button', { name: /小槿/ })).toBeEnabled();
  const characters = await request.get(`${apiBase}/api/communities/${communityId}/characters`, {
    params: { player_id: playerId },
  });
  expect((await characters.json())[0].memory_mode).toBe('simple');
});
