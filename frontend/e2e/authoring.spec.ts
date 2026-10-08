import { expect, test, type APIRequestContext } from '@playwright/test';

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

test('起始屏要求名字和描述，提交后进入向导并出现在草稿列表', async ({ page }) => {
  const name = `阿岚 ${suffix}`;
  await page.goto('/app/characters/authoring/new');
  await expect(page.getByRole('heading', { name: '先告诉我，TA 是谁？' })).toBeVisible();

  const start = page.getByRole('button', { name: '开始创作' });
  await expect(start).toBeDisabled();
  await page.getByPlaceholder('比如：阿岚').fill(name);
  await expect(start).toBeDisabled();
  await page.getByPlaceholder(/深夜食堂门口/).fill('话不多，但什么都看在眼里。');
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

  await page.locator('input[maxlength="80"]').fill(`冲突 ${suffix} 改`);
  await page.getByRole('button', { name: '保存修改' }).click();

  await expect(page.getByText(/草稿已被其他操作更新/)).toBeVisible();
});

test('基础章请求创作灵感：无模型凭据时明示不可用，有凭据时进入构思', async ({ page, request }) => {
  const draft = await seedDraft(request, `灵感 ${suffix}`);
  await page.goto(`/app/characters/authoring/${draft.draft_id}`);

  await page.getByRole('button', { name: '请 TA 起草' }).click();

  // 两种环境都是真实结果：没配凭据返回 503；配了凭据则候选进入处理中。
  await expect(
    page.getByRole('alert').filter({ hasText: /authoring_model_unavailable/ })
      .or(page.getByText('构思中…')),
  ).toBeVisible({ timeout: 20000 });
});
