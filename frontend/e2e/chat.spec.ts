import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * 聊天主流程的端到端验证，对运行中的真实后端执行。
 *
 * 前置数据由接口创建，界面只验证读取与交互结果：写入路径由接口契约保证，
 * 逐个界面入口点覆盖会显著拉长用例，且失败时难以区分是界面还是数据问题。
 */

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
const suffix = Date.now().toString(36);

const playerId = `e2e-player-${suffix}`;
const peerId = `e2e-peer-${suffix}`;
const communityId = `e2e-community-${suffix}`;
const communityName = '端到端社群';
const lobbyId = `${communityId}-lobby`;
const blueprintId = 'xiaojin';

/**
 * 走界面保存与注册的玩家标识固定，不用时间戳。
 *
 * 契约没有删除玩家的接口，每次运行新建一个玩家会持续累积；固定标识让用例
 * 第二次运行时进入「已注册」分支，两条路径都被覆盖且数据不再增长。
 */
const newcomerId = 'e2e-newcomer';
const welcomeId = 'e2e-welcome';
/** 用于验证「未注册」的标识。用例只读取它，不会创建。 */
const absentId = 'e2e-absent';

const subject = {
  playerId,
  playerDisplayName: '端到端玩家',
  communityId,
  communityName,
};

async function create<T>(
  api: APIRequestContext,
  method: 'post' | 'put',
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await api.fetch(`${apiBase}${path}`, {
    method,
    ...(body === undefined ? {} : { data: body }),
  });
  expect(response.ok(), `${method.toUpperCase()} ${path} 返回 ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

test.beforeAll(async ({ request }) => {
  // 已注册分支需要一个稳定存在的玩家：契约没有删除接口，重复创建返回 409。
  const existing = await request.post(`${apiBase}/api/players`, {
    data: { player_id: newcomerId, display_name: '界面新人' },
  });
  expect([200, 201, 409]).toContain(existing.status());

  await create(request, 'post', '/api/players', { player_id: playerId, display_name: '端到端玩家' });
  await create(request, 'post', '/api/players', { player_id: peerId, display_name: '同席' });
  await create(request, 'post', '/api/communities', {
    player_id: playerId,
    name: communityName,
    community_id: communityId,
    timezone: 'UTC',
  });
  await create(request, 'put', `/api/communities/${communityId}/players/${peerId}`);
  const character = await create<{ character_id: string }>(
    request,
    'post',
    `/api/communities/${communityId}/characters`,
    { player_id: playerId, blueprint_id: blueprintId },
  );
  await create(request, 'post', `/api/communities/${communityId}/conversations`, {
    player_id: playerId,
    kind: 'group',
    conversation_id: lobbyId,
    actors: [
      { kind: 'player', actor_id: playerId },
      { kind: 'player', actor_id: peerId },
      { kind: 'character', actor_id: character.character_id },
    ],
  });
  await create(request, 'post', `/api/conversations/${lobbyId}/messages`, {
    player_id: peerId,
    client_message_id: `e2e-seed-${suffix}`,
    text: '我这边还是偏淡，明天带一壶回来对比。',
    mentions: [],
    reply_to_message_id: null,
  });
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript((value) => {
    window.localStorage.setItem('echo-commons.subject.v1', JSON.stringify(value));
  }, subject);
});

test('会话列表按群聊分组并显示服务端预览', async ({ page }) => {
  await page.goto('/app/chat');
  await expect(page.getByText('群聊', { exact: true })).toBeVisible();
  // 群聊在契约里没有名称字段，列表显示会话标识。
  await expect(page.getByText(lobbyId, { exact: true })).toBeVisible();
  await expect(page.getByText(/我这边还是偏淡/)).toBeVisible();
});

test('群聊标题由会话成员派生，消息显示服务端名称', async ({ page }) => {
  await page.goto(`/app/chat/${lobbyId}`);
  // 契约里会话没有名称字段，标题取除自己外的成员名；成员顺序由服务端给出。
  await expect(page.getByRole('main')).toContainText('小槿');
  await expect(page.getByRole('main')).toContainText('同席');
  await expect(page.getByRole('main')).toContainText('我这边还是偏淡');
});

test('发送的消息出现在消息流中', async ({ page }) => {
  await page.goto(`/app/chat/${lobbyId}`);
  const text = `端到端消息 ${suffix}`;
  await page.getByPlaceholder('Enter 发送，Shift+Enter 换行').fill(text);
  await page.keyboard.press('Enter');
  await expect(page.getByRole('main')).toContainText(text);
});

test('可从社群成员建立私聊并进入新会话', async ({ page }) => {
  await page.goto('/app/chat');
  await page.getByRole('button', { name: '新建' }).click();

  const dialog = page.locator('div.fixed');
  await dialog.getByRole('button', { name: '私聊' }).click();
  await dialog.getByRole('button', { name: /小槿/ }).click();
  await dialog.getByRole('button', { name: '创建' }).click();

  await expect(page).toHaveURL(new RegExp(`/app/chat/(?!.*lobby).+`));
  await expect(page.getByRole('main')).toContainText('私聊');
});

test('本地身份按后端状态给出注册或保存入口', async ({ page, request }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/setup');

  // 未注册：给出注册入口，且不因为输入了标识就写入后端。
  await page.getByLabel('玩家标识').fill(absentId);
  await expect(page.getByText('后端没有这个玩家，进入时会先注册。')).toBeVisible();
  await expect(page.getByRole('button', { name: '注册并进入' })).toBeVisible();
  const untouched = await request.get(`${apiBase}/api/players/${absentId}`);
  expect(untouched.status()).toBe(404);

  // 已注册：保存本地身份即可进入，不需要再注册一次。
  await page.getByLabel('玩家标识').fill(newcomerId);
  await page.getByLabel('显示名称').fill('界面新人');
  await expect(page.getByText('后端已有这个玩家。')).toBeVisible();
  await page.getByRole('button', { name: '保存并进入' }).click();

  await expect(page).toHaveURL(/\/app\/chat$/);
  await expect(page.getByText('界面新人')).toBeVisible();
  // 身份在后端不存在时，列表区会直接显示后端的 404 文案。
  await expect(page.getByText('Player does not exist')).toHaveCount(0);
});

test('未注册玩家可从界面对话并注册', async ({ page, request }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto('/app/setup');

  await page.getByLabel('玩家标识').fill(welcomeId);
  await page.getByLabel('显示名称').fill('界面新人');
  await expect(page.getByText(/后端(没有|已有)这个玩家/)).toBeVisible();

  const register = page.getByRole('button', { name: '注册并进入' });
  if ((await register.count()) > 0) {
    await register.click();
    const created = await request.get(`${apiBase}/api/players/${welcomeId}`);
    expect(created.ok()).toBe(true);
  } else {
    await page.getByRole('button', { name: '保存并进入' }).click();
  }

  await expect(page).toHaveURL(/\/app\/chat$/);
  await expect(page.getByText('界面新人')).toBeVisible();
});
