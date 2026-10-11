import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * 自定义人物创作的端到端验证，对运行中的真实后端执行。
 *
 * 候选生成依赖模型凭据：无凭据时后端返回 503 authoring_model_unavailable，
 * 有用例同时接受「构思中」与「不可用」两种真实结果。需要模型的完整定稿路径
 * 在服务端 tests/infrastructure/test_character_authoring.py 中以 model 标记覆盖。
 */

const apiBase = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8765';
const suffix = Date.now().toString(36);

const playerId = `e2e-author-${suffix}`;
const subject = {
  playerId,
  playerDisplayName: '创作端到端玩家',
  communityId: null,
  communityName: null,
};

async function api<T>(
  request: APIRequestContext,
  method: 'get' | 'post' | 'put',
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await request.fetch(`${apiBase}${path}`, {
    method,
    ...(body === undefined ? {} : { data: body }),
  });
  expect(response.ok(), `${method.toUpperCase()} ${path} 返回 ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

interface SeedDraft {
  readonly draft_id: string;
  readonly revision: number;
  readonly content: Record<string, unknown>;
}

async function seedDraft(request: APIRequestContext, name: string): Promise<SeedDraft> {
  // 草稿编号契约要求 UUID，不能用可读的测试拼接标识。
  const draftId = crypto.randomUUID();
  return api<SeedDraft>(request, 'post', '/api/character-drafts', {
    player_id: playerId,
    draft_id: draftId,
    display_name: name,
    description: `端到端预置草稿 ${suffix}`,
    story: '',
    interview: [],
    avatar_url: null,
  });
}

/** 播种基础与故事都已定稿的草稿，可直接进入对谈章。 */
async function seedInterviewReadyDraft(request: APIRequestContext, name: string): Promise<SeedDraft> {
  let draft = await api<SeedDraft>(request, 'post', '/api/character-drafts', {
    player_id: playerId,
    draft_id: crypto.randomUUID(),
    display_name: name,
    description: `端到端对谈草稿 ${suffix}`,
    story: 'TA 在海边小镇长大，跟着祖父学修船，后来离开故乡再没回去。',
    interview: [],
    avatar_url: null,
    profile: '夜班司机，话少，观察力强，凌晨固定去同一家面馆。',
    voice: '短句、多停顿，偶尔冷幽默。',
    relational_dynamics: '不主动谈自己，对愿意听的人会慢慢多说。',
  });
  draft = await api<SeedDraft>(
    request,
    'post',
    `/api/character-drafts/${draft.draft_id}/stages/basic/confirm`,
    { player_id: playerId, expected_revision: draft.revision },
  );
  return api<SeedDraft>(
    request,
    'post',
    `/api/character-drafts/${draft.draft_id}/stages/story/confirm`,
    { player_id: playerId, expected_revision: draft.revision },
  );
}

async function openInterviewRun(page: Page, request: APIRequestContext) {
  const draft = await seedInterviewReadyDraft(request, `采访控制 ${crypto.randomUUID()}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);
  await page.getByRole('button', { name: '对谈 人物采访', exact: true }).click();
  await page.getByRole('button', { name: '开始选择问题（默认十五题）' }).click();
  await page.getByRole('button', { name: '暂存本章', exact: true }).click();
  await page.getByRole('button', { name: '灵感代答' }).click();
  await page.locator('summary').filter({ hasText: '通读三份正文' }).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '审核通过', exact: true }).click();
  const run = page.getByRole('button', { name: /为 15 个未回答的问题请 TA 回答/ });
  await expect(run).toBeEnabled();
  const saved = await api<SeedDraft>(request, 'get', `/api/character-drafts/${draft.draft_id}?player_id=${playerId}`);
  return { draft: saved, run };
}

for (const leave of [false, true]) {
  test(`真实模型采访${leave ? '离开页面' : '停止'}后不接受本批候选`, async ({ page, request }) => {
    test.skip(process.env.E2E_REAL_MODELS !== '1', '需要真实模型凭据');
    test.setTimeout(180_000);
    const { draft, run } = await openInterviewRun(page, request);
    const generated = leave ? null : page.waitForResponse(response => response.request().method() === 'POST'
      && response.url().endsWith(`/character-drafts/${draft.draft_id}/candidates`), { timeout: 150_000 });
    const started = page.waitForRequest(outgoing => outgoing.method() === 'POST'
      && outgoing.url().endsWith(`/character-drafts/${draft.draft_id}/candidates`));
    const accepts: string[] = [];
    page.on('request', outgoing => {
      if (outgoing.method() === 'POST' && outgoing.url().includes(`/character-drafts/${draft.draft_id}/candidates/`)
        && outgoing.url().endsWith('/accept')) accepts.push(outgoing.url());
    });
    await run.click();
    const outgoing = await started;
    if (leave) {
      await page.getByRole('link', { name: /返回角色/ }).press('Enter');
      await expect(page).toHaveURL(/\/app\/characters$/);
    }
    else await page.getByRole('button', { name: '停止', exact: true }).click();
    if (generated) {
      const response = await generated;
      expect(response.ok()).toBe(true);
      expect((await response.json()).status).toBe('completed');
    } else {
      const candidateId = outgoing.postDataJSON().candidate_id;
      await expect.poll(async () => {
        const candidate = await api<{ status: string }>(request, 'get',
          `/api/character-drafts/${draft.draft_id}/candidates/${candidateId}?player_id=${playerId}`);
        return candidate.status;
      }, { timeout: 150_000, intervals: [1000, 2000] }).toBe('completed');
    }
    if (!leave) await expect(run).toBeEnabled();
    else await page.goto(`/app/characters/authoring/${draft.draft_id}`);
    const saved = await api<SeedDraft>(request, 'get', `/api/character-drafts/${draft.draft_id}?player_id=${playerId}`);
    expect(saved.revision).toBe(draft.revision);
    expect(saved.content).toEqual(draft.content);
    expect(accepts).toHaveLength(0);
  });
}

test('采访真实断网失败后恢复操作并可再次生成', async ({ page, request, context }) => {
  test.setTimeout(180_000);
  const { run } = await openInterviewRun(page, request);
  try {
    await context.setOffline(true);
    await run.click();
    await expect(page.getByText('未成功', { exact: true })).toBeVisible();
    await expect(run).toBeEnabled();
    await expect(page.getByRole('button', { name: '停止', exact: true })).toHaveCount(0);
  } finally {
    await context.setOffline(false);
  }
  await expect(page.getByPlaceholder('可以留空，也可以统一交代 TA 回答时的语气、要保留或回避的内容…')).toBeEnabled();
  const retried = page.waitForResponse(response => response.request().method() === 'POST'
    && response.url().includes('/character-drafts/') && response.url().endsWith('/candidates'), { timeout: 150_000 });
  await run.click();
  expect([201, 503]).toContain((await retried).status());
  const stop = page.getByRole('button', { name: '停止', exact: true });
  if (await stop.isVisible()) await stop.click();
  await expect(run).toBeEnabled();
});

test.beforeAll(async ({ request }) => {
  const existing = await request.post(`${apiBase}/api/players`, {
    data: { player_id: playerId, display_name: subject.playerDisplayName },
  });
  expect([200, 201, 409]).toContain(existing.status());
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript((value) => {
    window.localStorage.setItem('echo-commons.subject.v1', JSON.stringify(value));
  }, subject);
});

test('角色页给出两条创建路径，未选社群时模板创建禁用', async ({ page }) => {
  await page.goto('/app/characters');
  await expect(page.getByRole('button', { name: '创作自定义人物' })).toBeEnabled();
  await expect(page.getByRole('button', { name: '从模板创建' })).toBeDisabled();
  await expect(page.getByText(/自定义人物创作界面尚未接入/)).toHaveCount(0);
});

test('起始屏只需名字，提交后进入向导并出现在草稿列表', async ({ page }) => {
  const name = `阿岚 ${suffix}`;
  await page.goto('/app/characters/authoring/new');
  await expect(page.getByRole('heading', { name: '先告诉我，TA 是谁？' })).toBeVisible();

  const start = page.getByRole('button', { name: '开始创作' });
  await expect(start).toBeDisabled();
  await page.getByPlaceholder('比如：阿岚').fill(name);
  await expect(start).toBeEnabled();
  await start.click();

  await expect(page).toHaveURL(/\/app\/characters\/authoring\/[0-9a-f-]+$/);
  await expect(page.getByRole('heading', { name: '初识' })).toBeVisible();

  await page.goto('/app/characters');
  await expect(page.getByRole('heading', { name: '我的人物志' })).toBeVisible();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByText('创作中', { exact: true }).first()).toBeVisible();
});

test('预置草稿出现在列表，继续创作进入向导', async ({ page, request }) => {
  const draft = await seedDraft(request, `预置 ${suffix}`);
  await page.goto('/app/characters');
  await page.getByRole('button', { name: new RegExp(draft.content.display_name as string) }).click();
  await expect(page).toHaveURL(new RegExp(`/authoring/${draft.draft_id}$`));
  await expect(page.getByRole('heading', { name: '初识' })).toBeVisible();
});

for (const width of [1440, 390]) {
  test(`自介卡保存、模板差异和外貌生成入口 ${width}`, async ({ page, request, context }) => {
    await page.setViewportSize({ width, height: 1000 });
    const draft = await seedDraft(request, `自介 ${width} ${suffix}`);
    await page.goto(`/app/characters/authoring/${draft.draft_id}`);
    await page.getByRole('button', { name: '再次编辑', exact: true }).click();
    await page.getByRole('textbox', { name: '年龄', exact: true }).fill('约二十岁');
    await page.getByRole('textbox', { name: '身份或职业', exact: true }).fill('修理师');
    await page.getByRole('textbox', { name: '发型与发色', exact: true }).fill('黑色短发');
    await context.setOffline(true);
    try {
      await page.getByRole('button', { name: '生成角色形象' }).click();
      await expect(page.getByRole('textbox', { name: '发型与发色', exact: true })).toHaveValue('黑色短发');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '生成角色形象' })).toBeEnabled();
    } finally { await context.setOffline(false); }
    await page.getByRole('button', { name: '生成角色形象' }).click();
    const picker = page.getByRole('dialog', { name: '角色插画与头像' });
    await expect(picker.getByLabel('姿态和场景补充')).toBeVisible();
    await picker.getByRole('button', { name: '关闭', exact: true }).click();
    const saved = await api<SeedDraft>(request, 'get', `/api/character-drafts/${draft.draft_id}?player_id=${playerId}`);
    expect((saved.content.introduction as { appearance: { hair: string } }).appearance.hair).toBe('黑色短发');
    expect(saved.content.profile).toBe(draft.content.profile);
    await page.locator('summary').filter({ hasText: /^详细设定$/ }).click();
    await page.getByRole('button', { name: '按资料生成正文' }).click();
    const diff = page.getByRole('region', { name: '模板正文差异' });
    await expect(diff).toBeVisible();
    await diff.locator('summary').filter({ hasText: '人物档案' }).click();
    await expect(diff.getByText(/发型与发色：黑色短发/)).toBeVisible();
    await page.screenshot({ path: `../server/data/verification/u05-introduction-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: '接受模板正文' }).click();
    await expect(diff).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('textbox', { name: '年龄', exact: true })).toHaveValue('约二十岁');
    const accepted = await api<SeedDraft>(request, 'get', `/api/character-drafts/${draft.draft_id}?player_id=${playerId}`);
    expect(accepted.content.profile).toContain('黑色短发');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('草稿被其他操作更新后，界面保存给出冲突提示并重载', async ({ page, request }) => {
  const draft = await seedDraft(request, `冲突 ${suffix}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);
  await expect(page.getByRole('heading', { name: '初识' })).toBeVisible();

  // 在界面已载入旧版本后，用接口把服务端修订号向前推进一步。
  const latest = await api<SeedDraft>(request, 'get', `/api/character-drafts/${draft.draft_id}?player_id=${playerId}`);
  await api(request, 'put', `/api/character-drafts/${draft.draft_id}`, {
    player_id: playerId,
    expected_revision: latest.revision,
    content: { ...latest.content, description: `接口先改了一笔 ${suffix}` },
  });

  // 双态章节默认锁定，先进入编辑态才能改。
  await page.getByRole('button', { name: '再次编辑', exact: true }).click();
  await page.locator('input[maxlength="80"]').fill(`冲突 ${suffix} 改`);
  await page.getByRole('button', { name: '暂存本章', exact: true }).click();

  await expect(page.getByText(/草稿已被其他操作更新/)).toBeVisible();
});

test('向导内随时可经顶栏返回角色页', async ({ page, request }) => {
  const draft = await seedDraft(request, `返回 ${suffix}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);
  await expect(page.getByRole('link', { name: /返回角色/ })).toBeVisible();
});

test('对谈章默认十五题删减，暂存后锁定，AI 模块唯一并可就地审核正文', async ({ page, request }) => {
  test.setTimeout(180_000);
  const draft = await seedInterviewReadyDraft(request, `对谈 ${suffix}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);
  await page.getByRole('button', { name: '对谈' }).click();

  // 旧版误报横幅不应再出现。
  await expect(page.getByText('采访依据已失效')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始选择问题（默认十五题）' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '创作灵感 · 对谈回答' })).toHaveCount(0);

  await page.getByRole('button', { name: '开始选择问题（默认十五题）' }).click();
  await expect(page.getByText('✓ 保留')).toHaveCount(15);

  // 被移除的题不能误标「已答」：移除一题再保留回来。
  await page.locator('.grid button[aria-pressed="true"]').first().click();
  await expect(page.getByText('✓ 保留')).toHaveCount(14);
  await expect(page.getByText('已答', { exact: true })).toHaveCount(0);
  await page.locator('.grid button[aria-pressed="false"]').first().click();
  await expect(page.getByText('✓ 保留')).toHaveCount(15);

  await page.getByRole('button', { name: '暂存本章', exact: true }).click();

  // 暂存后进入核对态：卡片不可点、回答只读、唯一的 AI 模块出现。
  await expect(page.getByRole('button', { name: '再次编辑', exact: true })).toBeVisible();
  await expect(page.getByText('（尚未回答）').first()).toBeVisible();
  await page.getByRole('button', { name: '灵感代答' }).click();
  const panel = page.getByRole('heading', { name: '创作灵感 · 对谈回答' });
  await expect(panel).toHaveCount(1);

  // 选题保存使正文回到待审核，审核入口就在 AI 模块内。
  await page.locator('summary').filter({ hasText: '通读三份正文' }).click();
  await expect(page.getByText('身份与性格').first()).toBeVisible();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '审核通过', exact: true }).click();
  const run = page.getByRole('button', { name: /为 15 个未回答的问题请 TA 回答/ });
  await expect(run).toBeEnabled({ timeout: 10_000 });
  await run.click();

  // 真实结果两种都接受：模型可用时三批全部写入；无凭据时第一批失败并可继续。
  const finished = page.getByText('保留的问题都有回答了').or(page.getByText('未成功'));
  await expect(finished.first()).toBeVisible({ timeout: 150_000 });

  if (await page.getByText('保留的问题都有回答了').isVisible()) {
    await expect(page.getByText('✓ 已写入')).toHaveCount(3);
    await page.getByRole('button', { name: '确认人物采访', exact: true }).click();
    await expect(page.getByRole('button', { name: /继续：定格/ })).toBeVisible({ timeout: 10_000 });
  } else {
    await expect(page.getByRole('button', { name: /为 15 个未回答的问题请 TA 回答/ })).toBeVisible();
  }
});

test('基础章请求创作灵感：无模型凭据时明示不可用，有凭据时进入构思', async ({ page, request }) => {
  const draft = await seedDraft(request, `灵感 ${suffix}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);

  await page.getByRole('button', { name: '灵感助手' }).click();
  await page.getByRole('button', { name: '请 TA 起草' }).click();

  // 两种环境都是真实结果：没配凭据返回 503；配了凭据则候选进入处理中。
  await expect(
    page.getByRole('alert').filter({ hasText: /服务暂时不可用/ })
      .or(page.getByText('构思中…')),
  ).toBeVisible({ timeout: 20000 });
});
