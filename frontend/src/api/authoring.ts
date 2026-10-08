// 自定义人物创作的全部接口入口。
//
// 草稿归属于玩家而不是社群，因此每个请求都带 player_id；所有写操作都携带
// expected_revision，由后端做乐观并发复核。这里只负责发送与缓存失效，阶段
// 门控、候选过期等推导放在 lib/authoring.ts，后端 409 始终是最终权威。
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from './http';
import { queryKeys } from './queryKeys';
import { newUuid } from '@/lib/clientMessageId';

export type AuthoringDraft = SchemaOf<'DraftView'>;
export type AuthoringCandidate = SchemaOf<'CandidateView'>;
export type AuthoringTemplate = SchemaOf<'AuthoringTemplateView'>;
export type AuthoringContent = SchemaOf<'AuthoringContent'>;
export type AuthoringWorkflow = SchemaOf<'AuthoringWorkflow'>;
export type InterviewAnswer = SchemaOf<'InterviewAnswer'>;
export type BlueprintCard = SchemaOf<'BlueprintCard'>;
export type CustomBlueprint = SchemaOf<'CustomBlueprintView'>;
export type AuthoringOperation = AuthoringCandidate['operation'];
export type AuthoringStage = 'basic' | 'story' | 'interview';

interface Page<T> {
  readonly items: T[];
  readonly cursor: string | null;
  readonly has_more: boolean;
}

/** 处理中候选的轮询节奏。超期标记发生在后端读取时，节奏保持稳定即可。 */
const CANDIDATE_POLL_MS = 2_000;

/** 模板是随服务端版本分发的静态资源，一次会话内读取一次。 */
export function useAuthoringTemplate() {
  return useQuery({
    queryKey: queryKeys.authoring.template,
    queryFn: () => request<AuthoringTemplate>('/api/character-authoring/template'),
    staleTime: Infinity,
  });
}

/** 玩家的草稿分页，含未完成与已确认草稿。 */
export function useDrafts(playerId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.authoring.drafts(playerId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      request<Page<AuthoringDraft>>('/api/character-drafts', {
        query: { player_id: playerId, cursor: pageParam },
      }),
    getNextPageParam: (page) => (page.has_more ? page.cursor : undefined),
    enabled: playerId !== '',
  });
}

export function useDraft(playerId: string, draftId: string) {
  return useQuery({
    queryKey: queryKeys.authoring.draft(playerId, draftId),
    queryFn: () =>
      request<AuthoringDraft>(`/api/character-drafts/${encodeURIComponent(draftId)}`, {
        query: { player_id: playerId },
      }),
    enabled: playerId !== '' && draftId !== '',
  });
}

export interface CreateDraftInput {
  readonly playerId: string;
  readonly displayName: string;
  readonly description: string;
  readonly avatarUrl?: string | null;
}

/** 建立草稿。draft_id 在客户端生成，同请求重试由后端幂等处理。 */
export function useCreateDraft() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateDraftInput) => {
      const body: SchemaOf<'CreateDraft'> = {
        player_id: input.playerId,
        draft_id: newUuid(),
        display_name: input.displayName,
        description: input.description,
        story: '',
        interview: [],
        avatar_url: input.avatarUrl ?? null,
      };
      return request<AuthoringDraft>('/api/character-drafts', { method: 'POST', body });
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(draft.owner_player_id, draft.draft_id), draft);
      void client.invalidateQueries({
        queryKey: ['authoring', draft.owner_player_id, 'drafts'],
      });
    },
  });
}

/** 作者手工编辑：PUT 提交完整 content，按后端返回更新当前草稿。 */
export function useSaveDraft(playerId: string, draftId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { readonly expectedRevision: number; readonly content: AuthoringContent }) => {
      const body: SchemaOf<'UpdateDraft'> = {
        player_id: playerId,
        expected_revision: input.expectedRevision,
        content: input.content,
      };
      return request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}`,
        { method: 'PUT', body },
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(playerId, draftId), draft);
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

/** 已固定人物复制为新草稿；新编号由客户端生成。 */
export function useCopyDraft(playerId: string, draftId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => {
      const body: SchemaOf<'CopyDraft'> = { player_id: playerId, draft_id: newUuid() };
      return request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/copy`,
        { method: 'POST', body },
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(playerId, draft.draft_id), draft);
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

export interface GenerateCandidateInput {
  readonly candidateId: string;
  readonly expectedRevision: number;
  readonly operation: AuthoringOperation;
  readonly instruction?: string;
  /** 仅采访候选使用：本批一至五个已选题目编号。 */
  readonly questionIds?: readonly string[] | undefined;
}

/** 请求生成候选。同步等待后候选仍可能是 processing，由 useCandidate 轮询。 */
export function useGenerateCandidate(playerId: string, draftId: string) {
  return useMutation({
    mutationFn: (input: GenerateCandidateInput) => {
      const common = {
        player_id: playerId,
        candidate_id: input.candidateId,
        expected_revision: input.expectedRevision,
        instruction: input.instruction ?? '',
      };
      const body =
        input.operation === 'interview'
          ? ({ ...common, operation: 'interview' as const, question_ids: [...(input.questionIds ?? [])] })
          : { ...common, operation: input.operation };
      return request<AuthoringCandidate>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates`,
        { method: 'POST', body },
      );
    },
  });
}

/**
 * 读取候选并在处理中轮询。
 *
 * 超过截止时间的 processing 候选要等后端在读取时标记，因此这里不把本地
 * 到期当作失败，「正在确认状态」的表达由界面按 deadline_utc 推导。
 */
export function useCandidate(
  playerId: string,
  draftId: string,
  candidateId: string | null,
) {
  return useQuery({
    queryKey: queryKeys.authoring.candidate(playerId, draftId, candidateId ?? ''),
    queryFn: () =>
      request<AuthoringCandidate>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates/${encodeURIComponent(candidateId ?? '')}`,
        { query: { player_id: playerId } },
      ),
    enabled: playerId !== '' && candidateId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === 'processing' ? CANDIDATE_POLL_MS : false,
  });
}

/** 接受候选。后端按操作范围合并并返回新草稿，前端不自行合并。 */
export function useAcceptCandidate(playerId: string, draftId: string, candidateId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (expectedRevision: number) => {
      const body: SchemaOf<'DraftAction'> = {
        player_id: playerId,
        expected_revision: expectedRevision,
      };
      return request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/candidates/${encodeURIComponent(candidateId)}/accept`,
        { method: 'POST', body },
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(playerId, draftId), draft);
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

export function useConfirmStage(playerId: string, draftId: string, stage: AuthoringStage) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (expectedRevision: number) => {
      const body: SchemaOf<'DraftAction'> = {
        player_id: playerId,
        expected_revision: expectedRevision,
      };
      return request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/stages/${stage}/confirm`,
        { method: 'POST', body },
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(playerId, draftId), draft);
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

/** 作者声明三份运行正文与材料一致。 */
export function useConfirmDocuments(playerId: string, draftId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (expectedRevision: number) => {
      const body: SchemaOf<'ConfirmDocuments'> = {
        player_id: playerId,
        expected_revision: expectedRevision,
        acknowledge_documents_match: true,
      };
      return request<AuthoringDraft>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/documents/confirm`,
        { method: 'POST', body },
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(queryKeys.authoring.draft(playerId, draftId), draft);
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

/** 最终固定，返回不可变的自定义人物资源；重复确认由后端返回原资源。 */
export function useConfirmDraft(playerId: string, draftId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (expectedRevision: number) => {
      const body: SchemaOf<'ConfirmDraft'> = {
        player_id: playerId,
        expected_revision: expectedRevision,
        acknowledge_fixed_background: true,
      };
      return request<CustomBlueprint>(
        `/api/character-drafts/${encodeURIComponent(draftId)}/confirm`,
        { method: 'POST', body },
      );
    },
    onSuccess: (blueprint) => {
      void client.invalidateQueries({
        queryKey: queryKeys.authoring.draft(playerId, draftId),
      });
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'blueprints'] });
      void client.invalidateQueries({ queryKey: ['authoring', playerId, 'drafts'] });
    },
  });
}

/** 已固定的自定义人物卡片分页（不含正文）。 */
export function useCustomBlueprints(playerId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.authoring.blueprints(playerId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      request<Page<BlueprintCard>>('/api/custom-blueprints', {
        query: { player_id: playerId, cursor: pageParam },
      }),
    getNextPageParam: (page) => (page.has_more ? page.cursor : undefined),
    enabled: playerId !== '',
  });
}
