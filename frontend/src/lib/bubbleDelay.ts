/**
 * 多气泡的入场延迟。
 *
 * 角色的一次回应可能分成几个气泡依次发出。界面把它们错开一小段时间，
 * 让一次回应读起来是分次发出，而不是一条长消息。延迟只是表现层的事：
 * 入库仍是一条消息，也不向后端逐个发送。
 *
 * 节奏要快。真实感来自间隔不一致，而不是间隔长：固定一段很长的停顿只会
 * 让界面变慢，因此单段延迟有上限，最长的一段也不会让人等。
 */

/** 第一段之间的固定间隔。够看出是两次动作，又不至于让人等。 */
const GAP_MS = 150;

/** 每字带来的额外间隔。长段落的发送时间自然更久。 */
const PER_CHAR_MS = 4;

/** 单段能贡献的最大间隔。防止长段落把后面几段推得太远。 */
const MAX_CONTRIBUTION_MS = 420;

/**
 * 按各段长度算出每段的延迟。
 *
 * 第 i 段的延迟由它前面所有段落累加得到，因此每段只需要看自己有多长：
 * 前面说过的话越长，下一次开口就越晚。首段没有前文，延迟为零。
 */
export function bubbleDelays(lengths: readonly number[]): number[] {
  const delays: number[] = [];
  let elapsed = 0;

  for (let index = 0; index < lengths.length; index += 1) {
    delays.push(elapsed);
    if (index + 1 >= lengths.length) break;
    const spoken = lengths[index] ?? 0;
    elapsed += GAP_MS + Math.min(spoken * PER_CHAR_MS, MAX_CONTRIBUTION_MS);
  }

  return delays;
}