// 角色配色由 character_id 派生，同一角色在头像、气泡、提及与棋子标记中始终同色。
// 不使用图片资产：聊天场景中首字加纯色已足够辨识，游戏场景由头像组件
// 承担棋子标记职责，见 docs/03-page-design.md 第 4 节。

/** 头像底色与前景色：深色底上的中性档位，白字可读。 */
const AVATAR_LIGHTNESS = 38;
const AVATAR_CHROMA = 0.12;
const AVATAR_TEXT_LIGHTNESS = 93;
const AVATAR_TEXT_CHROMA = 0.04;

/** 强调色：角色名、提及与状态使用，需要在深色底上清晰可读。 */
const ACCENT_LIGHTNESS = 78;
const ACCENT_CHROMA = 0.13;

/** FNV-1a 32 位散列。 */
function hash32(text: string): number {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/**
 * 由标识派生色相，返回 0—359 的整数。
 *
 * 先做 32 位散列再乘黄金角并取模，避免相邻或结构相近的标识落在相近色相上；
 * 直接对散列取模会让 `character-1` 与 `character-2` 这类标识颜色难以区分。
 */
export function characterHue(identity: string): number {
  return Math.round((hash32(identity) * 137.508) % 360);
}

export interface Rgb {
  readonly background: string;
  readonly foreground: string;
}

/** 头像配色。字形与底色同色相，仅明度不同，保证同一角色观感一致。 */
export function avatarColors(identity: string): Rgb {
  const hue = characterHue(identity);
  return {
    background: `oklch(${AVATAR_LIGHTNESS}% ${AVATAR_CHROMA} ${hue})`,
    foreground: `oklch(${AVATAR_TEXT_LIGHTNESS}% ${AVATAR_TEXT_CHROMA} ${hue})`,
  };
}

/** 强调色：角色名、提及高亮与状态文字。 */
export function accentColor(identity: string): string {
  return `oklch(${ACCENT_LIGHTNESS}% ${ACCENT_CHROMA} ${characterHue(identity)})`;
}

/**
 * 把长文本拆成多个气泡。
 *
 * 契约中一次角色回应保存为一条完整消息，界面可以按显示需要拆成多个气泡，
 * 但不向后端逐个发送。因此拆分只发生在渲染侧，入库与发送仍是一条。
 *
 * 按句末标点断句，优先在句号、问号、叹号、分号处断开；找不到标点时按
 * 长度硬切，保证单条消息不会渲染成一个超长气泡。
 */
export function splitForBubbles(text: string, maxLength = 48): string[] {
  const trimmed = text.trim();
  if (trimmed.length === 0) return [];
  if (trimmed.length <= maxLength) return [trimmed];

  const clauses = trimmed.split(/(?<=[。！？；!?;])/);
  const bubbles: string[] = [];
  let current = '';

  for (const clause of clauses) {
    if (clause === '') continue;
    if (current === '') {
      current = clause;
    } else if (current.length + clause.length <= maxLength) {
      current += clause;
    } else {
      bubbles.push(current);
      current = clause;
    }
    // 单条子句本身就超长时硬切，避免出现无法断开的超长气泡。
    while (current.length > maxLength) {
      bubbles.push(current.slice(0, maxLength));
      current = current.slice(maxLength);
    }
  }

  if (current !== '') bubbles.push(current);
  return bubbles;
}
