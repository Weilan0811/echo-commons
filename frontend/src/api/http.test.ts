import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiBaseUrl, pageOrigin, request } from './http';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiBaseUrl', () => {
  it('未配置时使用后端默认监听地址', () => {
    expect(apiBaseUrl()).toBe('http://127.0.0.1:8765');
  });
});

describe('request', () => {
  it('成功时返回解析后的响应体', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok', service: 'echo' })),
    );

    await expect(request<{ status: string }>('/health/live')).resolves.toEqual({
      status: 'ok',
      service: 'echo',
    });
  });

  it('把 error 信封归一为 ApiError，保留业务错误码', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(409, { error: { code: 'idempotency_conflict', message: '内容不一致' } }),
      ),
    );

    const error = await request('/api/conversations/c1/messages', {
      method: 'POST',
      body: {},
    }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.code).toBe('idempotency_conflict');
    expect(apiError.message).toBe('内容不一致');
    expect(apiError.retryable).toBe(false);
  });

  it('把 422 的 detail 数组归一为字段错误', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(422, { detail: [{ loc: ['body', 'name'], msg: 'Field required' }] }),
        ),
    );

    const error = await request('/api/communities', { method: 'POST', body: {} }).catch(
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe('validation_error');
    expect(apiError.fieldErrors).toEqual([{ location: ['body', 'name'], message: 'Field required' }]);
  });

  it('网络不可达时给出可重试错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed to fetch')));

    const error = await request('/health/live').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(0);
    expect(apiError.code).toBe('network_unavailable');
    expect(apiError.retryable).toBe(true);
  });

  it('连接失败提示同时点出跨域拒绝，并显示后端地址与页面来源', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('failed to fetch')));

    const error = (await request('/health/live').catch((e: unknown) => e)) as ApiError;

    // 浏览器不区分「后端未启动」与「被跨域拒绝」，提示必须覆盖两种可能，
    // 否则会把排查方向引向错误的一侧。
    expect(error.message).toContain('无法连接后端或被跨域策略拒绝');
    expect(error.message).toContain('http://127.0.0.1:8765');
    expect(error.message).toContain(pageOrigin());
  });

  it('503 标记为可重试，供界面按策略重试同一请求', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(503, { status: 'unavailable', database: 'down' })),
    );

    const error = await request('/health/ready').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).retryable).toBe(true);
  });

  it('跳过未定义的查询参数', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal('fetch', fetchMock);

    await request('/api/conversations/c1/messages', {
      query: { player_id: 'alice', cursor: undefined },
    });

    expect(fetchMock.mock.calls[0]?.[0].toString()).toBe(
      'http://127.0.0.1:8765/api/conversations/c1/messages?player_id=alice',
    );
  });
});
