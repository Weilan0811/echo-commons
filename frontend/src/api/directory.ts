// 社群目录与建立会话所需的写入入口。
//
// 展示身份统一取自 /api 下的公开接口：会话成员、社群成员与角色都返回
// PublicDisplay（公开身份与可选头像），因此会话标题、头像与提及候选不再
// 需要从消息正文推断，也不再依赖 /internal 路径。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from './http';
import { queryKeys } from './queryKeys';

type CommunityCard = SchemaOf<'CommunityCard'>;
type CommunityView = SchemaOf<'CommunityView'>;
type PublicDisplay = SchemaOf<'PublicDisplay'>;
type CharacterView = SchemaOf<'CharacterView'>;
type BlueprintView = SchemaOf<'BlueprintView'>;
type PlayerView = SchemaOf<'PlayerView'>;
type ActorRef = SchemaOf<'ActorRef'>;
type ConversationView = SchemaOf<'ConversationView'>;
type CreateCommunity = SchemaOf<'CreateCommunity'>;
type RegisterPlayer = SchemaOf<'RegisterPlayer'>;
type CreateCharacter = SchemaOf<'CreateCharacter'>;
type CreateConversation = SchemaOf<'CreateConversation'>;

export type { CommunityCard, PublicDisplay, CharacterView, ActorRef, ConversationView };

interface Page<T> {
  readonly items: T[];
  readonly cursor: string | null;
  readonly has_more: boolean;
}

/** 社群名称与时区。数量少，读取一次后按需刷新即可。 */
const DIRECTORY_STALE_MS = 30_000;

/** 社群世界时间由会话推进，节奏远慢于消息，因此按分钟级刷新。 */
const COMMUNITY_POLL_MS = 60_000;

/**
 * 社群详情。
 *
 * 社群卡片只有名称与时区，世界时间只在详情里返回，因此顶栏要显示世界时间
 * 必须读取详情。它同时给出时区，格式化时不再猜测本地时区。
 */
export function useCommunity(playerId: string, communityId: string | null) {
  return useQuery({
    queryKey: queryKeys.directory.community(playerId, communityId ?? ''),
    queryFn: () =>
      request<CommunityView>(`/api/communities/${communityId}`, { query: { player_id: playerId } }),
    enabled: playerId !== '' && communityId !== null && communityId !== '',
    staleTime: DIRECTORY_STALE_MS,
    refetchInterval: COMMUNITY_POLL_MS,
  });
}

/** 当前玩家已加入的社群。 */
export function useJoinedCommunities(playerId: string) {
  return useQuery({
    queryKey: queryKeys.directory.communities(playerId),
    queryFn: () =>
      request<Page<CommunityCard>>('/api/communities', {
        query: { player_id: playerId, scope: 'joined' },
      }),
    enabled: playerId !== '',
    staleTime: DIRECTORY_STALE_MS,
  });
}

/** 社群成员身份，供新建会话时选择参与者。 */
export function useCommunityMembers(playerId: string, communityId: string | null) {
  return useQuery({
    queryKey: queryKeys.directory.communityMembers(playerId, communityId ?? ''),
    queryFn: () =>
      request<Page<PublicDisplay>>(`/api/communities/${communityId}/members`, {
        query: { player_id: playerId },
      }),
    enabled: playerId !== '' && communityId !== null && communityId !== '',
    staleTime: DIRECTORY_STALE_MS,
  });
}

/** 会话成员身份。会话成员是会话的子集，与社群全体成员不同，两者不可互换。 */
export function useConversationMembers(playerId: string, conversationId: string) {
  return useQuery({
    queryKey: queryKeys.directory.conversationMembers(playerId, conversationId),
    queryFn: () =>
      request<Page<PublicDisplay>>(`/api/conversations/${conversationId}/members`, {
        query: { player_id: playerId },
      }),
    enabled: playerId !== '' && conversationId !== '',
    staleTime: DIRECTORY_STALE_MS,
  });
}

/** 社群内的角色。 */
export function useCommunityCharacters(playerId: string, communityId: string | null) {
  return useQuery({
    queryKey: queryKeys.directory.characters(playerId, communityId ?? ''),
    queryFn: () =>
      request<CharacterView[]>(`/api/communities/${communityId}/characters`, {
        query: { player_id: playerId },
      }),
    enabled: playerId !== '' && communityId !== null && communityId !== '',
    staleTime: DIRECTORY_STALE_MS,
    refetchInterval: (query) =>
      query.state.data?.some((character) => character.memory_status === 'preparing')
        ? 4000 : false,
  });
}

/** 可用人物模板。创建角色时提供选择，不让使用者手填标识。 */
export function useBlueprints() {
  return useQuery({
    queryKey: queryKeys.directory.blueprints,
    queryFn: () => request<BlueprintView[]>('/api/blueprints'),
    staleTime: Infinity,
  });
}

/**
 * 读取玩家身份。
 *
 * 本地身份可以指向一个后端没有的玩家：标识由使用者手填，没有账户体系兜底。
 * 界面因此需要先问一次「这个玩家存在吗」，把「填错标识」和「新玩家」分开，
 * 而不是让后续每个读取都返回 404。
 */
export function usePlayer(playerId: string) {
  return useQuery({
    queryKey: queryKeys.directory.player(playerId),
    queryFn: () => request<PlayerView>(`/api/players/${encodeURIComponent(playerId)}`),
    enabled: playerId !== '',
    staleTime: DIRECTORY_STALE_MS,
    // 不存在是有效答案，需要在填写变化后重新询问。
    retry: false,
  });
}

/** 注册玩家。后端尚无账户认证，标识由使用者指定。 */
export function useRegisterPlayer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { playerId: string; displayName: string }) => {
      const body: RegisterPlayer = {
        player_id: input.playerId,
        display_name: input.displayName,
      };
      return request<PlayerView>('/api/players', { method: 'POST', body });
    },
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: queryKeys.directory.player(result.player_id) });
    },
  });
}

/** 创建社群。发起人自动成为成员，创建完成后直接进入该社群。 */
export function useCreateCommunity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      playerId: string;
      name: string;
      communityId: string | null;
      timezone: string;
      coverRef?: string | null;
    }) => {
      const body: CreateCommunity = {
        player_id: input.playerId,
        name: input.name,
        community_id: input.communityId,
        timezone: input.timezone,
        cover_kind: input.coverRef ? 'preset' : null,
        cover_ref: input.coverRef ?? null,
      };
      return request<CommunityView>('/api/communities', { method: 'POST', body });
    },
    onSuccess: (_result, input) => {
      void client.invalidateQueries({ queryKey: queryKeys.directory.communities(input.playerId) });
    },
  });
}

export function useUpdateCommunity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { communityId: string; body: SchemaOf<'UpdateCommunityStatus'> | SchemaOf<'UpdateCommunityAppearance'>; kind: 'status' | 'appearance' }) =>
      request<CommunityView>(`/api/communities/${input.communityId}/${input.kind}`, {
        method: 'PATCH', body: input.body,
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['directory'] });
      void client.invalidateQueries({ queryKey: ['admin', 'community'] });
      void client.invalidateQueries({ queryKey: ['admin', 'communities'] });
    },
  });
}

/**
 * 加入社群。
 *
 * 现有玩家想进入他人的社群时唯一可用的入口：社群成员列表只有读取接口，
 * 没有直接添加成员的写入接口。
 */
export function useJoinCommunity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { communityId: string; playerId: string }) =>
      request(`/api/communities/${input.communityId}/players/${input.playerId}`, {
        method: 'PUT',
      }),
    onSuccess: (_result, input) => {
      void client.invalidateQueries({ queryKey: queryKeys.directory.communities(input.playerId) });
    },
  });
}

/** 从模板或自定义人物在社群内创建角色。模板入口固定 simple，创作向导可选 full。 */
export function useCreateCharacter() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      communityId: string;
      playerId: string;
      blueprintId: string;
      memoryMode?: 'simple' | 'full';
    }) => {
      const body: CreateCharacter = {
        player_id: input.playerId,
        blueprint_id: input.blueprintId,
        memory_mode: input.memoryMode ?? 'simple',
      };
      return request<CharacterView>(`/api/communities/${input.communityId}/characters`, {
        method: 'POST',
        body,
      });
    },
    onSuccess: (_result, input) => {
      void client.invalidateQueries({
        queryKey: queryKeys.directory.characters(input.playerId, input.communityId),
      });
      void client.invalidateQueries({ queryKey: queryKeys.directory.communityMembers(input.playerId, input.communityId) });
    },
  });
}

/** 准备失败后由使用者明确重试，状态继续以服务端返回为准。 */
export function useRetryCharacterMemory(playerId: string, communityId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (characterId: string) =>
      request<CharacterView>(`/api/communities/${communityId}/characters/${characterId}/memory/retry`, {
        method: 'POST',
        body: { player_id: playerId } satisfies SchemaOf<'RetryMemory'>,
      }),
    onSuccess: (character) => {
      client.setQueryData<CharacterView[]>(
        queryKeys.directory.characters(playerId, communityId ?? ''),
        (current) => current?.map((item) => item.character_id === character.character_id ? character : item),
      );
      void client.invalidateQueries({ queryKey: queryKeys.directory.characters(playerId, communityId ?? '') });
    },
  });
}

/** 建立会话。参与者必须是社群成员，服务端据此建立成员区间。 */
export function useCreateConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      communityId: string;
      playerId: string;
      kind: 'group' | 'direct';
      actors: readonly ActorRef[];
    }) => {
      const body: CreateConversation = {
        player_id: input.playerId,
        kind: input.kind,
        actors: [...input.actors],
      };
      return request<ConversationView>(`/api/communities/${input.communityId}/conversations`, {
        method: 'POST',
        body,
      });
    },
    onSuccess: (_result, input) => {
      void client.invalidateQueries({
        queryKey: queryKeys.directory.communityMembers(input.playerId, input.communityId),
      });
      void client.invalidateQueries({ queryKey: queryKeys.conversations.lists(input.playerId) });
    },
  });
}
