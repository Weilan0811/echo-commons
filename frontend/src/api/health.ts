import { useQuery } from '@tanstack/react-query';
import { queryKeys } from './queryKeys';
import { request } from './http';

/**
 * 健康检查在 OpenAPI 契约中没有响应模型（内容为 unknown），
 * 字段依据 server/docs/reference/http-api.md 第 5 节，
 * 类型依据真实后端返回确认：`database` 为布尔，`workers` 为名称到状态的映射。
 */
export interface LiveStatus {
  readonly status: string;
  readonly service: string;
  readonly version: string;
}

export interface ReadyStatus {
  readonly status: string;
  readonly database: boolean;
  readonly workers_enabled: boolean;
  readonly workers: Readonly<Record<string, string>>;
}

/** 存活检查不请求模型，用于确认进程与接口地址可达。 */
export function useLiveStatus() {
  return useQuery({
    queryKey: queryKeys.health.live,
    queryFn: () => request<LiveStatus>('/health/live'),
    retry: 1,
  });
}

/** 就绪检查反映数据库与后台工作状态。 */
export function useReadyStatus() {
  return useQuery({
    queryKey: queryKeys.health.ready,
    queryFn: () => request<ReadyStatus>('/health/ready'),
    retry: 1,
  });
}