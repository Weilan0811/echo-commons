import { randomUUID } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';

test('创建者邀请、撤回并重新邀请角色，正确显示行动方', async ({
  page,
  request,
}) => {
  const suffix = randomUUID();
  const playerId = `game-role-player-${suffix}`;
  const communityId = `game-role-community-${suffix}`;
  const characterId = `game-role-character-${suffix}`;
  expect(
    (
      await request.post(`${apiBase}/api/players`, {
        data: { player_id: playerId, display_name: '角色参与验证' },
      })
    ).ok(),
  ).toBe(true);
  expect(
    (
      await request.post(`${apiBase}/api/communities`, {
        data: {
          player_id: playerId,
          community_id: communityId,
          name: '角色参与验证',
          timezone: 'UTC',
        },
      })
    ).ok(),
  ).toBe(true);
  expect(
    (
      await request.post(`${apiBase}/api/communities/${communityId}/characters`, {
        data: {
          player_id: playerId,
          blueprint_id: 'xiaojin',
          character_id: characterId,
          memory_mode: 'simple',
        },
      })
    ).ok(),
  ).toBe(true);
  await identify(page, playerId, '角色参与验证', communityId);
  await page.goto('/app/games');
  await page.getByRole('link', { name: '查看五子棋对局', exact: true }).click();
  await page.getByRole('button', { name: '创建对局', exact: true }).click();
  const invite = async () => {
    await page.getByRole('button', { name: '邀请角色执白', exact: true }).click();
    await page.getByText('可以入座', { exact: true }).click();
    await expect(page.getByRole('radio', { name: /可以入座/ })).toBeChecked();
    await page.getByRole('button', { name: '邀请入座', exact: true }).click();
    await expect(page.getByRole('button', { name: '开始对局', exact: true })).toBeVisible();
  };
  await invite();
  await page.getByRole('button', { name: /^撤回/ }).click();
  await page.getByRole('button', { name: '确认撤回', exact: true }).click();
  await invite();
  await page.getByRole('button', { name: '开始对局', exact: true }).click();
  await page.getByRole('button', { name: /^五子棋棋盘/ }).press('Enter');
  await expect(page.getByText('1 手落子', { exact: true })).toBeVisible();
  await expect(page.getByText(/轮到.*行动/)).toBeVisible();
});

async function identify(page: Page, playerId: string, name: string, communityId: string) {
  await page.goto('/app/identity');
  await page.getByRole('textbox', { name: '玩家标识', exact: true }).fill(playerId);
  await page.getByRole('textbox', { name: '显示名称', exact: true }).fill(name);
  await page.getByRole('textbox', { name: /当前社群标识/ }).fill(communityId);
  await page.getByRole('button', { name: '保存并进入', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/chat$/);
}

async function place(page: Page, x: number, y: number, count: number) {
  const board = page.getByRole('button', { name: /^五子棋棋盘/ });
  await expect(board).toBeVisible();
  for (let index = 0; index < Math.abs(x - 7); index++)
    await board.press(x < 7 ? 'ArrowLeft' : 'ArrowRight');
  for (let index = 0; index < Math.abs(y - 7); index++)
    await board.press(y < 7 ? 'ArrowUp' : 'ArrowDown');
  await board.press('Enter');
  await expect(page.getByText(`${count} 手落子`, { exact: true })).toBeVisible();
}

test('两名真人完成入座、重新加入、九步获胜、聊天和结束活动', async ({
  browser,
  request,
  baseURL,
}) => {
  const suffix = randomUUID();
  const alice = `game-browser-alice-${suffix}`;
  const bob = `game-browser-bob-${suffix}`;
  const communityId = `game-browser-${suffix}`;
  for (const [player_id, display_name] of [
    [alice, '整局验证甲'],
    [bob, '整局验证乙'],
  ]) {
    const response = await request.post(`${apiBase}/api/players`, {
      data: { player_id, display_name },
    });
    expect(response.ok()).toBe(true);
  }
  expect(
    (
      await request.post(`${apiBase}/api/communities`, {
        data: {
          player_id: alice,
          community_id: communityId,
          name: '真人整局验证',
          timezone: 'UTC',
        },
      })
    ).ok(),
  ).toBe(true);
  expect((await request.put(`${apiBase}/api/communities/${communityId}/players/${bob}`)).ok()).toBe(
    true,
  );
  if (!baseURL) throw new Error('请配置真实前端地址。');
  const aliceContext = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 900 },
  });
  const bobContext = await browser.newContext({ baseURL, viewport: { width: 1440, height: 900 } });
  try {
    const first = await aliceContext.newPage();
    const second = await bobContext.newPage();
    await identify(first, alice, '整局验证甲', communityId);
    await identify(second, bob, '整局验证乙', communityId);
    await first.goto('/app/games');
    await first.getByRole('link', { name: '查看五子棋对局', exact: true }).click();
    await first.getByRole('button', { name: '创建对局', exact: true }).dblclick();
    await expect(first).toHaveURL(/\/app\/games\/[a-f0-9]+$/);
    const gameUrl = first.url();
    await second.goto(gameUrl);
    await second.getByRole('button', { name: '入座', exact: true }).click();
    await second.getByRole('button', { name: '离开对局', exact: true }).click();
    await second.getByRole('button', { name: '确认离开', exact: true }).click();
    await second.getByRole('button', { name: '入座', exact: true }).click();
    await first.getByRole('button', { name: '开始对局', exact: true }).click();
    for (let move = 0; move < 9; move++) {
      await place(
        move % 2 === 0 ? first : second,
        4 + Math.floor(move / 2),
        move % 2 === 0 ? 7 : 8,
        move + 1,
      );
    }
    await expect(first.getByText('整局验证甲赢得了这一局', { exact: true })).toBeVisible();
    await expect(second.getByText('整局验证甲赢得了这一局', { exact: true })).toBeVisible();
    await first.getByRole('textbox').fill('结算后继续交流。');
    await first.getByRole('button', { name: '发送', exact: true }).click();
    await expect(second.getByText('结算后继续交流。', { exact: true })).toBeVisible();
    const gameId = gameUrl.split('/').at(-1)!;
    const read = () =>
      request
        .get(`${apiBase}/api/games/${gameId}`, { params: { player_id: alice } })
        .then((response) => response.json());
    const before = await read();
    await first.getByRole('button', { name: '结束活动', exact: true }).click();
    await first.getByRole('button', { name: '确认结束活动', exact: true }).click();
    await expect(second.getByText('活动已结束，消息保留在这里。', { exact: true })).toBeVisible();
    expect((await read()).game.state_version).toBe(before.game.state_version);
    await expect(second.getByRole('button', { name: '对局记录', exact: true })).toHaveCount(0);
    await second.getByRole('button', { name: '规则与说明', exact: true }).click();
    await expect(second.getByRole('dialog', { name: '规则与说明' })).toBeVisible();
    await second.getByRole('button', { name: '关闭规则说明', exact: true }).click();
    await second.setViewportSize({ width: 390, height: 844 });
    await expect(second.getByRole('button', { name: '棋盘', exact: true })).toBeVisible();
    const dimensions = await second.locator('svg.gomoku-board').boundingBox();
    expect(dimensions!.width).toBeGreaterThan(320);
    expect(dimensions!.width).toBeLessThan(390);
    await second.screenshot({ path: test.info().outputPath('game-finished-mobile.png') });
  } finally {
    await aliceContext.close();
    await bobContext.close();
  }
});
