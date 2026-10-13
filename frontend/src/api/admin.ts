// 管理查询与明确的维护操作。
//
// 管理接口会返回角色内心、冻结输入与记忆正文。排障时需要看到它们，但它们
// 绝不能进入玩家缓存：这里的查询键与玩家端完全分开，页面也不共用。
//
// 服务默认只监听 127.0.0.1 且没有管理员账户认证，前端直接请求 /internal，
// 不携带凭据。远程部署前需要单独设计访问控制。
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from './http';
import { queryKeys } from './queryKeys';

export type AdminCommunity = SchemaOf<'CommunityView'>;
export type AdminCharacter = SchemaOf<'CharacterDetail'>;
export type AdminConversation = SchemaOf<'ConversationDetail'>;
export type AdminMessage = SchemaOf<'MessageSummary'>;
export type AdminMessageDetail = SchemaOf<'MessageDetail'>;
export type AdminTurn = SchemaOf<'TurnSummary'>;
export type AdminTurnDetail = SchemaOf<'TurnDetail'>;
export type AdminTask = SchemaOf<'TaskSummary'>;
export type AdminTaskDetail = SchemaOf<'TaskDetail'>;
export type AdminMember = SchemaOf<'CommunityMemberView'>;
export type AdminInterval = SchemaOf<'MemberInterval'>;
export type AdminPlayer = SchemaOf<'PlayerView'>;
export type AdminRelationship = SchemaOf<'RelationshipInspection'>;
export type AdminEvidence = SchemaOf<'EvidenceView'>;
export type AdminReflection = SchemaOf<'ReflectionSummary'>;
export type AdminTrace = SchemaOf<'TraceInspection'>;

export function useAdminCoreMemory(communityId: string, characterId: string) {
  return useQuery({
    queryKey: queryKeys.admin.coreMemory(communityId, characterId),
    queryFn: () => request<SchemaOf<'CoreMemoryInspection'>>(
      `/internal/communities/${communityId}/characters/${characterId}/reflection/core-memory`,
    ),
    refetchInterval: (query) => ['pending', 'running', 'retry_wait'].includes(
      query.state.data?.refresh?.status ?? '',
    ) ? 3000 : false,
  });
}

export function useRefreshCoreMemory(communityId: string, characterId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (requestId: string) => request<SchemaOf<'ScheduleResult'>>(
      `/internal/communities/${communityId}/characters/${characterId}/reflection/core-memory`,
      { method: 'POST', body: { request_id: requestId } },
    ),
    onSuccess: () => cache.invalidateQueries({
      queryKey: queryKeys.admin.character(communityId, characterId),
    }),
  });
}

export function useRefreshRelationshipAttitudes(communityId: string, characterId: string) {
  const cache = useQueryClient();
  return useMutation({
    networkMode: 'always',
    mutationFn: (body: SchemaOf<'RelationshipRefreshRequest'>) =>
      request<SchemaOf<'RelationshipRefreshResult'>[]>(
        `/internal/communities/${communityId}/characters/${characterId}/reflection/relationship-attitudes`,
        { method: 'POST', body },
      ),
    onSuccess: () => cache.invalidateQueries({
      queryKey: queryKeys.admin.character(communityId, characterId),
    }),
  });
}

/** 反思图详情：图、节点、产物、审核与实际写入的事实一次返回。 */
export type AdminReflectionDetail = SchemaOf<'ReflectionDetail'>;

/**
 * 节点输入。input_ready 为假时 input 为空：空输入不是「输入是空的」，而是「输入还没形成」。
 */
export type AdminNodeInput = SchemaOf<'NodeInspection'>;
/** 记忆分项。五类共用一个路径，类别由 MemoryCollection 给出。 */
/**
 * 记忆索引状态。
 *
 * 索引状态和失败项直接使用契约生成的字段，管理页面展示材料编号与失败原因。
 */
export type AdminMemoryIndex = SchemaOf<'MemoryIndexStatus'>;

/** 记忆索引状态。检索结果异常时先看这里，再决定是否需要重建。 */
export function useAdminMemoryIndex(communityId: string | null, characterId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.characterMemoryIndex(communityId ?? '', characterId ?? ''),
    queryFn: () =>
      request<AdminMemoryIndex>(`/internal/characters/${characterId}/memory-index`, {
        query: { community_id: communityId },
      }),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}
/** 产物中的逐步执行记录，回答「模型当时做了什么」。 */
export type AdminAgentStep = SchemaOf<'AgentStep'>;

/** 记忆详情：按 record_kind 分别展示三类记录。 */
export type AdminMemoryDetail =
  | SchemaOf<'SegmentDetail'>
  | SchemaOf<'DigestDetail'>
  | SchemaOf<'EntryDetail'>;

export type AdminMemoryItem =
  | SchemaOf<'SegmentSummary'>
  | SchemaOf<'DigestSummary'>
  | SchemaOf<'EntrySummary'>;

export const MEMORY_COLLECTIONS = [
  { value: 'segments', label: '材料段' },
  { value: 'digests', label: '连续摘要' },
  { value: 'entries', label: '长期页' },
] as const;

/** 管理分页。所有管理列表都是这个形状。 */
export interface AdminPage<T> {
  readonly items: readonly T[];
  readonly cursor: string | null;
  readonly has_more: boolean;
}

/**
 * 管理数据由后台工作进程推动，没有推送接口。
 *
 * 轮询比玩家端慢：这里用于排障，秒级刷新只会让私有正文不停闪动。
 */
const ADMIN_STALE_MS = 5_000;
const ADMIN_POLL_MS = 15_000;

interface ListOptions {
  readonly cursor?: string | null;
  readonly limit?: number;
}

export function useAdminCommunities(options: ListOptions = {}) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.communities(cursor, options.limit),
    queryFn: () =>
      request<AdminPage<AdminCommunity>>('/internal/communities', {
        query: withCursor({ limit: options.limit }, cursor),
      }),
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminCommunitySearch(search: string) {
  return useInfiniteQuery({
    queryKey: ['admin', 'communities', 'search', search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<AdminPage<AdminCommunity>>('/internal/communities', {
      query: { q: search, cursor: pageParam, limit: 20 }, signal,
    }),
    getNextPageParam: (page) => page.has_more ? page.cursor ?? undefined : undefined,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminCommunity(communityId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.community(communityId ?? ''),
    queryFn: () => request<AdminCommunity>(`/internal/communities/${communityId}`),
    enabled: communityId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminCommunityMembers(communityId: string | null, options: ListOptions = {}) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.communityMembers(communityId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminMember>>(`/internal/communities/${communityId}/members`, {
        query: withCursor({ limit: options.limit }, cursor),
      }),
    enabled: communityId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/**
 * 社群全部会话。
 *
 * 不按玩家过滤，这是管理侧与玩家端的根本差别：这里能看到 archived 与当前
 * 玩家已离开的会话。
 */
export function useAdminConversations(
  communityId: string | null,
  options: ListOptions & { readonly kind?: string; readonly status?: string } = {},
) {
  const cursor = options.cursor ?? null;
  const kind = options.kind ?? '';
  const status = options.status ?? '';
  return useQuery({
    queryKey: queryKeys.admin.communityConversations(communityId ?? '', cursor, kind, status),
    queryFn: () =>
      request<AdminPage<AdminConversation>>(`/internal/communities/${communityId}/conversations`, {
        query: withCursor({ kind, status, limit: options.limit }, cursor),
      }),
    enabled: communityId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminCharacters(communityId: string | null, options: ListOptions = {}) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.communityCharacters(communityId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminCharacter>>(`/internal/communities/${communityId}/characters`, {
        query: withCursor({ limit: options.limit }, cursor),
      }),
    enabled: communityId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}
export function useAdminCharacter(communityId: string | null, characterId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.character(communityId ?? '', characterId ?? ''),
    queryFn: () =>
      request<AdminCharacter>(`/internal/communities/${communityId}/characters/${characterId}`),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminCharacterStates(communityId: string | null, characterId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.characterStates(communityId ?? '', characterId ?? ''),
    queryFn: () =>
      request<SchemaOf<'StateInspection'>>(
        `/internal/communities/${communityId}/characters/${characterId}/states`,
      ),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminRelationships(
  communityId: string | null,
  characterId: string | null,
  options: ListOptions = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.characterRelationships(communityId ?? '', characterId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminRelationship>>(
        `/internal/communities/${communityId}/characters/${characterId}/relationships`,
        { query: withCursor({ limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: (query) => query.state.data?.items.some((item) =>
      ['pending', 'running', 'retry_wait'].includes(item.attitude_refresh?.status ?? ''),
    ) ? 3000 : false,
  });
}

export function useAdminEvidence(
  communityId: string | null,
  characterId: string | null,
  target: { readonly kind: string; readonly id: string } | null,
  options: ListOptions = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.characterRelationshipEvidence(
      communityId ?? '',
      characterId ?? '',
      target?.kind ?? '',
      target?.id ?? '',
      cursor,
    ),
    queryFn: () =>
      request<AdminPage<AdminEvidence>>(
        `/internal/communities/${communityId}/characters/${characterId}` +
          `/relationships/${target?.kind}/${target?.id}/evidence`,
        { query: withCursor({ limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && characterId !== null && target !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/** 记忆。五类共用一个路径，类别是必填路径段。 */
export function useAdminMemory(
  communityId: string | null,
  characterId: string | null,
  collection: string,
  options: ListOptions & { readonly conversationId?: string } = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.characterMemory(communityId ?? '', characterId ?? '', collection, cursor),
    queryFn: () =>
      request<AdminPage<AdminMemoryItem>>(
        `/internal/communities/${communityId}/characters/${characterId}/memory/${collection}`,
        { query: withCursor({ conversation_id: options.conversationId, limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminMemoryRecord(
  communityId: string | null,
  characterId: string | null,
  collection: string,
  recordId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.characterMemoryRecord(
      communityId ?? '',
      characterId ?? '',
      collection,
      recordId ?? '',
    ),
    queryFn: () =>
      request<SchemaOf<'SegmentDetail'> | SchemaOf<'DigestDetail'> | SchemaOf<'EntryDetail'>>(
        `/internal/communities/${communityId}/characters/${characterId}` +
          `/memory/${collection}/${recordId}`,
      ),
    enabled: communityId !== null && characterId !== null && recordId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminReflectionRuns(
  communityId: string | null,
  characterId: string | null,
  options: ListOptions & { readonly status?: string } = {},
) {
  const cursor = options.cursor ?? null;
  const status = options.status ?? '';
  return useQuery({
    queryKey: queryKeys.admin.characterReflectionRuns(
      communityId ?? '',
      characterId ?? '',
      cursor,
      status,
    ),
    queryFn: () =>
      request<AdminPage<AdminReflection>>(
        `/internal/communities/${communityId}/characters/${characterId}/reflection/runs`,
        { query: withCursor({ status, limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && characterId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/** 反思图详情。图与节点一次返回，节点输入另按需读取。 */
export function useAdminReflectionRun(
  communityId: string | null,
  characterId: string | null,
  graphRunId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.reflectionRun(communityId ?? '', characterId ?? '', graphRunId ?? ''),
    queryFn: () =>
      request<AdminReflectionDetail>(`/internal/reflection/runs/${graphRunId}`, {
        query: { community_id: communityId, character_id: characterId },
      }),
    enabled: communityId !== null && characterId !== null && graphRunId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/**
 * 节点输入。
 *
 * 依赖未完成或节点未激活时后端返回 input_ready 为假且 input 为空。界面按
 * 未具备呈现，不能把空输入当成已经执行过的材料。
 */
export function useAdminNodeInput(
  communityId: string | null,
  characterId: string | null,
  graphRunId: string | null,
  nodeTaskId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.reflectionNodeInput(
      communityId ?? '',
      characterId ?? '',
      nodeTaskId ?? '',
    ),
    queryFn: () =>
      request<SchemaOf<'NodeInspection'>>(
        `/internal/reflection/runs/${graphRunId}/nodes/${nodeTaskId}/input`,
        { query: { community_id: communityId, character_id: characterId } },
      ),
    enabled:
      communityId !== null && characterId !== null && graphRunId !== null && nodeTaskId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}
export function useAdminConversation(communityId: string | null, conversationId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.conversation(communityId ?? '', conversationId ?? ''),
    queryFn: () =>
      request<AdminConversation>(`/internal/communities/${communityId}/conversations/${conversationId}`),
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminIntervals(
  communityId: string | null,
  conversationId: string | null,
  options: ListOptions = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.conversationMembers(communityId ?? '', conversationId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminInterval>>(
        `/internal/communities/${communityId}/conversations/${conversationId}/members`,
        { query: withCursor({ limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminMessages(
  communityId: string | null,
  conversationId: string | null,
  options: ListOptions = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.conversationMessages(communityId ?? '', conversationId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminMessage>>(
        `/internal/communities/${communityId}/conversations/${conversationId}/messages`,
        { query: withCursor({ limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminMessage(
  communityId: string | null,
  conversationId: string | null,
  messageId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.conversationMessage(
      communityId ?? '',
      conversationId ?? '',
      messageId ?? '',
    ),
    queryFn: () =>
      request<AdminMessageDetail>(
        `/internal/communities/${communityId}/conversations/${conversationId}/messages/${messageId}`,
      ),
    enabled: communityId !== null && conversationId !== null && messageId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminTurns(
  communityId: string | null,
  conversationId: string | null,
  options: ListOptions = {},
) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.conversationTurns(communityId ?? '', conversationId ?? '', cursor),
    queryFn: () =>
      request<AdminPage<AdminTurn>>(
        `/internal/communities/${communityId}/conversations/${conversationId}/turns`,
        { query: withCursor({ limit: options.limit }, cursor) },
      ),
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminTurn(
  communityId: string | null,
  conversationId: string | null,
  turnId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.conversationTurn(communityId ?? '', conversationId ?? '', turnId ?? ''),
    queryFn: () =>
      request<AdminTurnDetail>(
        `/internal/communities/${communityId}/conversations/${conversationId}/turns/${turnId}`,
      ),
    enabled: communityId !== null && conversationId !== null && turnId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminTasks(
  communityId: string | null,
  options: ListOptions & {
    readonly conversationId?: string;
    readonly characterId?: string;
    readonly status?: string;
  } = {},
) {
  const cursor = options.cursor ?? null;
  const conversationId = options.conversationId ?? '';
  const characterId = options.characterId ?? '';
  const status = options.status ?? '';
  return useQuery({
    queryKey: queryKeys.admin.communityTasks(communityId ?? '', cursor, conversationId, characterId, status),
    queryFn: () =>
      request<AdminPage<AdminTask>>(`/internal/communities/${communityId}/tasks`, {
        query: withCursor(
          {
            conversation_id: conversationId,
            character_id: characterId,
            status,
            limit: options.limit,
          },
          cursor,
        ),
      }),
    enabled: communityId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}
export function useAdminTask(
  communityId: string | null,
  characterId: string | null,
  taskId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.task(communityId ?? '', characterId ?? '', taskId ?? ''),
    queryFn: () =>
      request<AdminTaskDetail>(`/internal/characters/${characterId}/tasks/${taskId}`, {
        query: { community_id: communityId ?? '' },
      }),
    enabled: communityId !== null && characterId !== null && taskId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/** 执行链路按轮次读取，继续翻页直到覆盖会话全部记录。 */
export function useAdminTurnTasks(
  communityId: string | null,
  conversationId: string | null,
  turnId: string,
) {
  return useQuery({
    queryKey: [
      ...queryKeys.admin.conversationTurn(communityId ?? '', conversationId ?? '', turnId), 'tasks',
    ],
    queryFn: async () => {
      const tasks = await readAdminPages<AdminTask>(`/internal/communities/${communityId}/tasks`, {
        conversation_id: conversationId ?? '',
      });
      return tasks.filter((task) => task.social_turn_id === turnId);
    },
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

export function useAdminTurnMessages(
  communityId: string | null,
  conversationId: string | null,
  turnId: string,
) {
  return useQuery({
    queryKey: [
      ...queryKeys.admin.conversationTurn(communityId ?? '', conversationId ?? '', turnId), 'messages',
    ],
    queryFn: async () => {
      const messages = await readAdminPages<AdminMessage>(
        `/internal/communities/${communityId}/conversations/${conversationId}/messages`,
      );
      return messages.filter((message) => message.source_turn_id === turnId);
    },
    enabled: communityId !== null && conversationId !== null,
    staleTime: ADMIN_STALE_MS,
    refetchInterval: ADMIN_POLL_MS,
  });
}

async function readAdminPages<T>(path: string, query: Readonly<Record<string, string>> = {}) {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const page: AdminPage<T> = await request(path, { query: { ...query, limit: 200, cursor } });
    items.push(...page.items);
    cursor = page.has_more ? page.cursor : null;
  } while (cursor !== null);
  return items;
}

/**
 * 冻结上下文。
 *
 * 私有正文，只在任务详情里按需读取。契约过滤已清除的内心正文，保留来源
 * 编号；这里不把「无正文」显示成空数组。
 */
export function useAdminTaskContext(
  communityId: string | null,
  characterId: string | null,
  taskId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.taskContext(communityId ?? '', characterId ?? '', taskId ?? ''),
    queryFn: () =>
      request<SchemaOf<'InspectedContext'>>(
        `/internal/characters/${characterId}/tasks/${taskId}/context`,
        { query: { community_id: communityId ?? '' } },
      ),
    enabled: communityId !== null && characterId !== null && taskId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminTrace(
  communityId: string | null,
  correlationId: string | null,
  characterId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.admin.trace(communityId ?? '', correlationId ?? '', characterId),
    queryFn: () =>
      request<AdminTrace>(`/internal/traces/${correlationId}`, {
        query: {
          community_id: communityId ?? '',
          ...(characterId === null ? {} : { character_id: characterId }),
        },
      }),
    enabled: communityId !== null && correlationId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

/** 玩家详情。只在展开某一行时读取，列表不重复请求。 */
export function useAdminPlayer(playerId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.player(playerId ?? ''),
    queryFn: () => request<AdminPlayer>(`/internal/players/${playerId}`),
    enabled: playerId !== null,
    staleTime: ADMIN_STALE_MS,
  });
}

export function useAdminPlayers(options: ListOptions = {}) {
  const cursor = options.cursor ?? null;
  return useQuery({
    queryKey: queryKeys.admin.players(cursor, options.limit),
    queryFn: () =>
      request<AdminPage<AdminPlayer>>('/internal/players', {
        query: withCursor({ limit: options.limit }, cursor),
      }),
    staleTime: ADMIN_STALE_MS,
  });
}

/**
 * 拼查询参数。
 *
 * 空字符串与 undefined 都表示不筛选：后端把这两种值当作参数缺省处理，
 * 传过去会让筛选看起来生效了但其实没有。
 */
function withCursor(
  base: Record<string, string | number | undefined>,
  cursor: string | null,
): Record<string, string | number> {
  const query: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(base)) {
    if (value !== undefined && value !== '') query[key] = value;
  }
  if (cursor !== null) query.cursor = cursor;
  return query;
}
