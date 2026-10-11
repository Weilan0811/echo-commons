import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';

test('完整模式的核心记忆通过正式接口安排重建并展示读取进度', async ({ page, request }) => {
  const identity = randomUUID();
  const player = `core-player-${identity}`;
  const community = `core-community-${identity}`;
  const character = `core-character-${identity}`;
  expect((await request.post(`${apiBase}/api/players`, {
    data: { player_id: player, display_name: '核心记忆验证者' },
  })).ok()).toBe(true);
  expect((await request.post(`${apiBase}/api/communities`, {
    data: { player_id: player, community_id: community, name: '核心记忆验证', timezone: 'UTC' },
  })).ok()).toBe(true);
  expect((await request.post(`${apiBase}/api/communities/${community}/characters`, {
    data: { player_id: player, character_id: character, blueprint_id: 'xiaojin', memory_mode: 'full' },
  })).ok()).toBe(true);
  await page.goto(`/admin/communities/${community}/characters/${character}`);
  const panel = page.getByRole('heading', { name: '核心记忆', exact: true }).locator('..').locator('..');
  await expect(panel.getByText('0 / 600 字符', { exact: true })).toBeVisible();
  const scheduled = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/reflection/core-memory'));
  await panel.getByRole('button', { name: '重建核心记忆', exact: true }).click();
  const response = await scheduled;
  expect(response.status()).toBe(202);
  const run = await response.json();
  await expect(panel.getByRole('button', { name: '正在重建…' })).toBeDisabled();
  await expect(panel.getByText('4 / 4；未读 0', { exact: true })).toBeVisible();
  await expect(panel.getByText('pending', { exact: true })).toBeVisible();
  const repeated = await request.post(response.url(), { data: response.request().postDataJSON() });
  expect((await repeated.json()).graph_run.graph_run_id).toBe(run.graph_run.graph_run_id);
  await panel.getByText('查看来源、生成结果与实际模型调用', { exact: true }).click();
  await expect(panel.getByText('view_refresh_planner', { exact: true }).first()).toBeVisible();
});
