// 查询键工厂：所有缓存键在此生成，页面不手写键数组。
//
// 契约要求游标绑定查询种类、玩家与筛选范围，且不能跨玩家、会话或协议使用。
// 因此会话、消息与阅读位置一律带 player_id，见 adr/0001。
export const queryKeys = {
  games: {
    types: ['games', 'types'] as const,
    scope: (playerId: string, communityId: string) => ['games', playerId, communityId] as const,
    detail: (playerId: string, communityId: string, gameId: string) =>
      ['games', playerId, communityId, gameId] as const,
    lists: (playerId: string, communityId: string) =>
      ['games', playerId, communityId, 'list'] as const,
    list: (playerId: string, communityId: string, type: string, status: string) =>
      ['games', playerId, communityId, 'list', type, status] as const,
    session: (playerId: string, communityId: string, gameId: string) =>
      ['games', playerId, communityId, gameId, 'session'] as const,
    candidates: (playerId: string, communityId: string, gameId: string) =>
      ['games', playerId, communityId, gameId, 'candidates'] as const,
    view: (playerId: string, communityId: string, gameId: string, participationId: string) =>
      ['games', playerId, communityId, gameId, 'view', participationId] as const,
  },
  health: {
    live: ['health', 'live'] as const,
    ready: ['health', 'ready'] as const,
  },

  communities: {
    list: (playerId: string) => ['communities', playerId] as const,
    members: (playerId: string, communityId: string) =>
      ['communities', communityId, 'members', playerId] as const,
  },

  conversations: {
    lists: (playerId: string) => ['conversations', 'list', playerId] as const,
    /** 玩家维度的会话列表，可按社群、成员关系与状态筛选。 */
    list: (playerId: string, communityId: string | null, view: string) =>
      ['conversations', 'list', playerId, communityId, view] as const,
    detail: (playerId: string, conversationId: string) =>
      ['conversations', conversationId, 'detail', playerId] as const,
    /** 消息增量读取，与历史读取是两套游标，键也不同。 */
    poll: (playerId: string, conversationId: string) =>
      ['conversations', conversationId, 'poll', playerId] as const,
    /** 历史读取：首次取最新，之后按 older_cursor 向前翻。 */
    history: (playerId: string, conversationId: string) =>
      ['conversations', conversationId, 'history', playerId] as const,
    turns: (playerId: string, conversationId: string) =>
      ['conversations', conversationId, 'turns', playerId] as const,
    read: (playerId: string, conversationId: string) =>
      ['conversations', conversationId, 'read', playerId] as const,
  },

  /**
   * 管理查询。
   *
   * 与玩家查询严格分开：管理接口会返回角色内心、冻结输入与记忆正文，
   * 这些内容不能进入玩家缓存，也不能被玩家页面读到。键的前缀不同只是第一
   * 道隔离，真正的边界是页面本身不共用。
   *
   * 游标绑定查询种类、范围与筛选条件，换范围必须从第一页重新读取，因此
   * 每个查询键都带上完整的范围参数，不复用上一层游标。
   */
  admin: {
    gameInspection: (communityId: string, conversationId: string) =>
      ['admin', 'community', communityId, 'conversation', conversationId, 'game'] as const,
    gameRecords: (communityId: string, conversationId: string, kind: string) =>
      [
        'admin',
        'community',
        communityId,
        'conversation',
        conversationId,
        'game',
        'records',
        kind,
      ] as const,
    playerGenerations: (playerId: string, kind: 'images' | 'candidates') =>
      ['admin', 'player', playerId, 'generations', kind] as const,
    // 社群列表与玩家列表一样靠增大 limit 加载更多，limit 必须进键。
    communities: (cursor: string | null, limit?: number) =>
      ['admin', 'communities', cursor, limit ?? null] as const,
    community: (communityId: string) => ['admin', 'community', communityId] as const,
    communityMembers: (communityId: string, cursor: string | null) =>
      ['admin', 'community', communityId, 'members', cursor] as const,
    communityCharacters: (communityId: string, cursor: string | null) =>
      ['admin', 'community', communityId, 'characters', cursor] as const,
    communityConversations: (
      communityId: string,
      cursor: string | null,
      kind: string,
      status: string,
    ) => ['admin', 'community', communityId, 'conversations', kind, status, cursor] as const,
    communityTasks: (
      communityId: string,
      cursor: string | null,
      conversationId: string,
      characterId: string,
      status: string,
    ) =>
      [
        'admin',
        'community',
        communityId,
        'tasks',
        conversationId,
        characterId,
        status,
        cursor,
      ] as const,
    // 玩家页用增大 limit 的方式加载更多，limit 必须进键，否则改 limit 不会重新请求。
    players: (cursor: string | null, limit?: number) =>
      ['admin', 'players', cursor, limit ?? null] as const,
    player: (playerId: string) => ['admin', 'player', playerId] as const,

    character: (communityId: string, characterId: string) =>
      ['admin', 'character', communityId, characterId] as const,
    characterStates: (communityId: string, characterId: string) =>
      ['admin', 'character', communityId, characterId, 'states'] as const,
    coreMemory: (communityId: string, characterId: string) =>
      ['admin', 'character', communityId, characterId, 'core-memory'] as const,
    characterRelationships: (communityId: string, characterId: string, cursor: string | null) =>
      ['admin', 'character', communityId, characterId, 'relationships', cursor] as const,
    characterRelationshipEvidence: (
      communityId: string,
      characterId: string,
      targetKind: string,
      targetId: string,
      cursor: string | null,
    ) =>
      [
        'admin',
        'character',
        communityId,
        characterId,
        'relationships',
        targetKind,
        targetId,
        'evidence',
        cursor,
      ] as const,
    characterMemory: (
      communityId: string,
      characterId: string,
      collection: string,
      cursor: string | null,
    ) => ['admin', 'character', communityId, characterId, 'memory', collection, cursor] as const,
    characterMemoryRecord: (
      communityId: string,
      characterId: string,
      collection: string,
      recordId: string,
    ) => ['admin', 'character', communityId, characterId, 'memory', collection, recordId] as const,
    characterMemoryIndex: (communityId: string, characterId: string) =>
      ['admin', 'character', communityId, characterId, 'memory-index'] as const,
    characterReflectionRuns: (
      communityId: string,
      characterId: string,
      cursor: string | null,
      status: string,
    ) => ['admin', 'character', communityId, characterId, 'reflection', status, cursor] as const,

    conversation: (communityId: string, conversationId: string) =>
      ['admin', 'conversation', communityId, conversationId] as const,
    conversationMembers: (communityId: string, conversationId: string, cursor: string | null) =>
      ['admin', 'conversation', communityId, conversationId, 'members', cursor] as const,
    conversationMessages: (communityId: string, conversationId: string, cursor: string | null) =>
      ['admin', 'conversation', communityId, conversationId, 'messages', cursor] as const,
    conversationMessage: (communityId: string, conversationId: string, messageId: string) =>
      ['admin', 'conversation', communityId, conversationId, 'message', messageId] as const,
    conversationTurns: (communityId: string, conversationId: string, cursor: string | null) =>
      ['admin', 'conversation', communityId, conversationId, 'turns', cursor] as const,
    conversationTurn: (communityId: string, conversationId: string, turnId: string) =>
      ['admin', 'conversation', communityId, conversationId, 'turn', turnId] as const,

    task: (communityId: string, characterId: string, taskId: string) =>
      ['admin', 'task', communityId, characterId, taskId] as const,
    taskContext: (communityId: string, characterId: string, taskId: string) =>
      ['admin', 'task', communityId, characterId, taskId, 'context'] as const,
    reflectionRun: (communityId: string, characterId: string, graphRunId: string) =>
      ['admin', 'reflection', communityId, characterId, graphRunId] as const,
    reflectionNodeInput: (communityId: string, characterId: string, nodeTaskId: string) =>
      ['admin', 'reflection', communityId, characterId, 'node', nodeTaskId, 'input'] as const,
    trace: (communityId: string, correlationId: string, characterId: string | null) =>
      ['admin', 'trace', communityId, characterId, correlationId] as const,
  },
  /**
   * 自定义人物创作。
   *
   * 草稿与候选都是玩家私有材料，键必须带 player_id；候选轮询是独立资源，
   * 与草稿明细分开缓存，候选接受后失效草稿，不反向写入候选缓存。
   */
  authoring: {
    template: ['authoring', 'template'] as const,
    drafts: (playerId: string) => ['authoring', playerId, 'drafts'] as const,
    draft: (playerId: string, draftId: string) =>
      ['authoring', playerId, 'draft', draftId] as const,
    candidate: (playerId: string, draftId: string, candidateId: string) =>
      ['authoring', playerId, 'draft', draftId, 'candidate', candidateId] as const,
    blueprints: (playerId: string) => ['authoring', playerId, 'blueprints'] as const,
  },

  /** 社群目录：成员身份、角色与模板。这些数据变动很慢，读取频率低于会话。 */
  directory: {
    blueprints: ['directory', 'blueprints'] as const,
    player: (playerId: string) => ['directory', 'player', playerId] as const,
    communities: (playerId: string) => ['directory', 'communities', playerId] as const,
    community: (playerId: string, communityId: string) =>
      ['directory', 'community', communityId, playerId] as const,
    communityMembers: (playerId: string, communityId: string) =>
      ['directory', 'community', communityId, 'members', playerId] as const,
    conversationMembers: (playerId: string, conversationId: string) =>
      ['directory', 'conversation', conversationId, 'members', playerId] as const,
    characters: (playerId: string, communityId: string) =>
      ['directory', 'community', communityId, 'characters', playerId] as const,
  },
} as const;
