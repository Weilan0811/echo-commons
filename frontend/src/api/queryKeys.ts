// 查询键工厂：所有缓存键在此生成，页面不手写键数组。
// 契约要求游标绑定社群、会话与读取玩家，且换玩家或会话时不能复用游标，
// 因此会话相关键必须包含这三段身份维度。见 adr/0001。
export const queryKeys = {
  health: {
    live: ['health', 'live'] as const,
    ready: ['health', 'ready'] as const,
  },
} as const;