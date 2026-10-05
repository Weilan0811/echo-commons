/**
 * 客户端幂等标识。
 *
 * 契约要求每次新输入生成独立标识，网络重试保持原标识和原字段：重复发送
 * 使用相同标识与相同内容返回原事实，内容冲突返回 409。因此标识必须在
 * 发送意图产生时生成一次，并在重试时复用，不能在每次请求时重新生成。
 */

/**
 * 生成一次发送意图的幂等标识。
 *
 * 优先使用平台的随机标识实现；不可用时退回时间戳与随机数组合，
 * 保证同一页面内连续两次发送不会得到相同标识。
 */
export function newClientMessageId(): string {
  const cryptoRef: Crypto | undefined = globalThis.crypto;
  if (cryptoRef !== undefined && typeof cryptoRef.randomUUID === 'function') {
    return cryptoRef.randomUUID();
  }
  const random = Math.floor(Math.random() * 0xffffffff).toString(16);
  return `${Date.now().toString(36)}-${random}`;
}

/**
 * 校验标识可用于发送。契约要求非空。
 */
export function isUsableClientMessageId(value: string): boolean {
  return value.trim() !== '';
}
