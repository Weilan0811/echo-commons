// 查询键工厂：所有缓存键在此生成，页面不手写键数组。
//
// 契约要求游标绑定查询种类、玩家与筛选范围，且不能跨玩家、会话或协议使用。
// 因此会话、消息与阅读位置一律带 player_id，见 adr/0001。
export const queryKeys = {
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
    /** 玩家维度的会话列表，可按社群、成员关系与状态筛选。 */
    list: (playerId: string, communityId: string | null, membership: string, status: string) =>
      ['conversations', 'list', playerId, communityId, membership, status] as const,
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
