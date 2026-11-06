import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

// 该验收会调用真实模型并完成整局，由显式环境变量启用。
test.skip(!process.env.E2E_ACTIVITY_ACCEPTANCE, '需要明确启用真实角色整局验收');
const api = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8877';

test('玩家从界面与两个角色完成飞行棋及赛后交流', async ({ page, request }, testInfo) => {
  test.setTimeout(90 * 60 * 1000);
  page.setDefaultTimeout(15000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const suffix = randomUUID();
  const resume = process.env.E2E_ACTIVITY_RESUME ? JSON.parse(process.env.E2E_ACTIVITY_RESUME) : null;
  const player = resume?.player ?? `aero-player-${suffix}`;
  const community = resume?.community ?? `aero-community-${suffix}`;
  const characters: string[] = resume?.characters ?? [`aero-first-${suffix}`, `aero-second-${suffix}`];
  const post = async (path: string, data: object) => {
    const response = await request.post(`${api}${path}`, { data });
    expect(response.ok(), await response.text()).toBe(true);
    return response.json();
  };
  if (!resume) {
    await post('/api/players', { player_id: player, display_name: '飞行棋玩家' });
    await post('/api/communities', {
      player_id: player, community_id: community, name: '飞行棋联合验收', timezone: 'Asia/Shanghai',
    });
    expect((await request.patch(`${api}/api/communities/${community}/status`, {
      data: { player_id: player, status: 'active', expected_version: 0 },
    })).ok()).toBe(true);
    for (const character of characters) {
      await post(`/api/communities/${community}/characters`, {
        player_id: player, blueprint_id: 'xiaojin', character_id: character, memory_mode: 'simple',
      });
    }
  }
  await page.goto('/app/identity');
  await page.getByRole('textbox', { name: '玩家标识', exact: true }).fill(player);
  await page.getByRole('textbox', { name: '显示名称', exact: true }).fill('飞行棋玩家');
  await page.getByRole('textbox', { name: /当前社群标识/ }).fill(community);
  await page.getByRole('button', { name: '保存并进入', exact: true }).click();
  let game: string;
  if (resume) {
    game = resume.game;
    await page.goto(`/app/games/${game}`);
  } else {
    await page.goto('/app/games');
    await page.getByRole('link', { name: '查看飞行棋对局', exact: true }).click();
    await page.getByRole('button', { name: '创建对局', exact: true }).click();
    await expect(page).toHaveURL(/\/app\/games\/[^/]+$/);
    game = page.url().split('/').at(-1)!;
    for (const [index, color] of ['黄方', '蓝方'].entries()) {
      await page.getByRole('button', { name: `邀请角色${color}`, exact: true }).click();
      await page.locator('label').filter({
        has: page.locator(`input[value="${characters[index]}"]`),
      }).click();
      await page.getByRole('button', { name: '邀请入座', exact: true }).click();
      await expect(page.getByRole('dialog')).toHaveCount(0);
    }
    await page.getByRole('button', { name: '开始对局', exact: true }).click();
  }
  console.log(`started game=${game} community=${community}`);
  const say = async (text: string) => {
    const input = page.locator('textarea');
    await input.fill(text);
    await input.press('Enter');
    await expect(input).toHaveValue('');
  };
  if (!resume) await say('一起玩吧！你们觉得谁会赢？有精彩的地方也聊聊，我要认真追上你们。');
  else if (process.env.E2E_ACTIVITY_NUDGE) await say('轮到你了，我们继续刚才这局吧。');
  const started = Date.now();
  let version = 0;
  let lastProgress = started;
  let finished: any;
  let interrupted = !!resume;
  while (Date.now() - started < 85 * 60 * 1000) {
    const response = await request.get(`${api}/api/games/${game}/view`, {
      params: { player_id: player },
    });
    expect(response.ok()).toBe(true);
    const view = await response.json();
    if (view.state_version !== version) {
      version = view.state_version;
      lastProgress = Date.now();
      if (version % 25 === 0) console.log(`game=${game} version=${version}`);
    }
    expect(Date.now() - lastProgress, `对局停在版本 ${version}`).toBeLessThan(120000);
    if (view.status === 'finished') { finished = view; break; }
    if (!interrupted && version > 35) {
      await say('哎呀，别光顾着赢呀，你们现在最担心谁？');
      interrupted = true;
    }
    const legal = view.opportunities[0]?.legal_actions ?? [];
    const submitted = legal.length ? page.waitForResponse(response =>
      response.url().endsWith(`/api/games/${game}/actions`) && response.request().method() === 'POST'
    ) : null;
    const button = (name: string) => page.getByRole('button', { name, exact: true });
    if (legal.some((a: any) => a.type === 'roll_dice')) await button('掷骰子').click();
    else if (legal.some((a: any) => a.type === 'fly_shortcut')) await button('沿虚线飞越').click();
    else if (legal.some((a: any) => a.type === 'jump_four')) await button('跳四格').click();
    else if (legal.length) {
      const own = view.state.planes.filter((p: any) => p.seat_id === 'red');
      const score = (a: any) => {
        const step = own.find((p: any) => p.plane_id === a.plane_id)?.step;
        if (a.type === 'take_off') return 70;
        if (a.type === 'return_penalty') return -(step ?? 0);
        return step + view.state.dice === 55 ? 1000 : (step ?? -1);
      };
      const chosen = [...legal].sort((a: any, b: any) => score(b) - score(a))[0];
      if (chosen.type === 'end_move') await button('结束移动').click();
      else await page.getByRole('button', {
        name: `红方第 ${chosen.plane_id} 号飞机，可行动`, exact: true,
      }).press('Enter');
    }
    if (submitted) expect((await submitted).ok()).toBe(true);
    await page.waitForTimeout(400);
  }
  expect(finished?.state.result?.winner_seat_id).toBeTruthy();
  await expect(page.getByText(/^(红方|黄方|蓝方)获胜$/)).toBeVisible();
  const session = await (await request.get(`${api}/api/games/${game}`, {
    params: { player_id: player },
  })).json();
  const history = async (conversation: string) => (await (await request.get(
    `${api}/api/conversations/${conversation}/messages/history`, { params: { player_id: player } },
  )).json()).messages;
  const latest = Math.max(...(await history(session.conversation.conversation_id)).map((m: any) => m.sequence));
  await say('恭喜获胜！刚才哪一刻最精彩？结束以后我们也记住这局吧。');
  await expect.poll(async () => (await history(session.conversation.conversation_id)).some(
    (m: any) => m.sender.kind === 'character' && m.sequence > latest,
  ), { timeout: 90000 }).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('finished.png'), fullPage: true });
  await page.getByRole('button', { name: '结束活动', exact: true }).click();
  await page.getByRole('button', { name: '确认结束活动', exact: true }).click();
  await expect(page.locator('textarea')).toHaveCount(0);
  const conversation = await post(`/api/communities/${community}/conversations`, {
    player_id: player, kind: 'group', conversation_id: randomUUID(),
    actors: [{ kind: 'player', actor_id: player },
      ...characters.map(character => ({ kind: 'character', actor_id: character }))],
  });
  await page.goto(`/app/chat/${conversation.conversation_id}`);
  await say('刚才那局飞行棋是谁赢了？你们最记得哪一幕？');
  await expect.poll(async () => (await history(conversation.conversation_id)).some(
    (m: any) => m.sender.kind === 'character',
  ), { timeout: 90000 }).toBe(true);
  await testInfo.attach('recall.json', {
    body: JSON.stringify(await history(conversation.conversation_id)), contentType: 'application/json',
  });
  await testInfo.attach('match.json', {
    body: JSON.stringify({ game, community, player, characters, elapsed_ms: Date.now() - started, finished }),
    contentType: 'application/json',
  });
});
