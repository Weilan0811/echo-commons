// 与后端契约耦合的唯一入口：错误形状归一、请求发送、响应解析。
// 字段与结构依据 server/docs/reference/openapi.json 生成的类型，不手工抄写。
import type { components } from './schema';

/** 契约中具名的数据类型。 */
export type SchemaName = keyof components['schemas'];

/** 按契约名取出数据类型，避免在页面里重复描述字段。 */
export type SchemaOf<T extends SchemaName> = components['schemas'][T];

export interface FieldError {
  readonly location: readonly (string | number)[];
  readonly message: string;
}

/**
 * 归一后的接口错误。
 *
 * 后端存在两种错误形状：400/404/409/500/503 返回
 * `{"error":{"code","message"}}`，422 返回 FastAPI 默认的 `detail` 数组。
 * 页面只处理本类型，不区分两种来源。
 */
export class ApiError extends Error {
  /** HTTP 状态码；网络或解析失败为 0。 */
  readonly status: number;
  /** 后端业务错误码；无法取得时为 `unknown`。 */
  readonly code: string;
  /** 422 的字段级错误，其他情况为空。 */
  readonly fieldErrors: readonly FieldError[];
  /** 503 与网络失败可按界面策略重试。 */
  readonly retryable: boolean;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    fieldErrors?: readonly FieldError[];
    retryable?: boolean;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.fieldErrors = init.fieldErrors ?? [];
    this.retryable = init.retryable ?? (init.status === 0 || init.status === 503);
  }
}

const DEFAULT_BASE_URL = 'http://127.0.0.1:8765';

type QueryValue = string | number | boolean;

/** 接口地址：环境变量优先，留空时使用后端默认监听地址。 */
export function apiBaseUrl(): string {
  const configured: unknown = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === 'string' && configured.trim().length > 0) {
    return configured.trim().replace(/\/+$/, '');
  }
  return DEFAULT_BASE_URL;
}

/**
 * 当前页面来源。跨域策略按此值匹配后端 cors_origins，
 * 因此连接失败时需要把它一并显示出来。
 */
export function pageOrigin(): string {
  if (typeof window === 'undefined' || window.location === null) return '未知来源';
  return window.location.origin;
}

export interface RequestOptions {
  readonly method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** null 与 undefined 都表示不传该查询参数。 */
  readonly query?: Readonly<Record<string, QueryValue | null | undefined>>;
  readonly body?: unknown;
  readonly signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** 把两种错误形状归一为 ApiError；无法解析时保留状态码与通用提示。 */
function toApiError(status: number, body: unknown): ApiError {
  if (isRecord(body) && isRecord(body.error)) {
    const { code, message } = body.error;
    return new ApiError({
      status,
      code: typeof code === 'string' ? code : 'unknown',
      message: typeof message === 'string' ? message : `请求失败（HTTP ${status}）`,
    });
  }

  if (isRecord(body) && Array.isArray(body.detail)) {
    const fieldErrors: FieldError[] = [];
    for (const item of body.detail) {
      if (!isRecord(item)) continue;
      const loc = Array.isArray(item.loc)
        ? item.loc.filter((part): part is string | number =>
            typeof part === 'string' || typeof part === 'number',
          )
        : [];
      fieldErrors.push({
        location: loc,
        message: typeof item.msg === 'string' ? item.msg : '字段校验失败',
      });
    }
    return new ApiError({
      status,
      code: 'validation_error',
      message: fieldErrors.length > 0 ? fieldErrors[0]!.message : '请求字段校验失败',
      fieldErrors,
    });
  }

  if (isRecord(body) && typeof body.detail === 'string') {
    return new ApiError({ status, code: 'unknown', message: body.detail });
  }

  return new ApiError({ status, code: 'unknown', message: `请求失败（HTTP ${status}）` });
}

/** 发送请求并返回解析后的响应体；失败一律抛出 ApiError。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal } = options;
  const url = new URL(path, apiBaseUrl());
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    // 浏览器不会说明 fetch 被拒的真正原因：后端未启动与被跨域策略拒绝
    // 都会走到这里，且后端日志可能仍是 200。因此提示需要同时给出两种可能，
    // 并显示页面来源，避免把排查方向引向错误的一侧。
    throw new ApiError({
      status: 0,
      code: 'network_unavailable',
      message:
        `无法连接后端或被跨域策略拒绝。` +
        `后端地址 ${apiBaseUrl()}，当前页面来源 ${pageOrigin()}。` +
        `请确认后端已启动，且其 server.cors_origins 包含当前页面来源。`,
    });
  }

  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    throw toApiError(response.status, payload);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}