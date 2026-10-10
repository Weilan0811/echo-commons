/**
 * 社群封面预设（随包官方素材）。
 *
 * 后端尚未提供 cover_kind/cover_ref 字段（见 docs/02-backend-interface-gaps.md
 * 3.3），在接口落地前，社群与群聊头图由前端按社群稳定映射到三张预设横幅；
 * 以后端返回为准时只需替换 resolveCover 的读取来源，调用方不变。
 */
export interface PresetCover {
  readonly id: string;
  /** 用于按社群名命中的俗称，命中时优先于散列。 */
  readonly matchNames: readonly string[];
  readonly url: string;
}

export const PRESET_COVERS: ReadonlyArray<PresetCover> = [
  { id: 'diner', matchNames: ['深夜食堂'], url: '/assets/covers/diner.webp' },
  { id: 'campus-dusk', matchNames: ['校园', '学校'], url: '/assets/covers/campus-dusk.webp' },
  { id: 'lakeside', matchNames: ['湖', '小镇'], url: '/assets/covers/lakeside.webp' },
];

/** FNV-1a 风格散列，保证同一社群永远落到同一张封面。 */
function hash32(text: string): number {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/**
 * 解析社群封面：名字命中俗称时用对应预设，否则按标识散列轮换。
 * 无封面场景（空标识）返回 null，由调用方用程序化渐变兜底。
 */
export function resolveCover(seed: string | null | undefined, displayName?: string | null): string | null {
  if (seed === null || seed === undefined || seed === '') return null;
  if (displayName) {
    const matched = PRESET_COVERS.find((cover) =>
      cover.matchNames.some((keyword) => displayName.includes(keyword)),
    );
    if (matched !== undefined) return matched.url;
  }
  return PRESET_COVERS[hash32(seed) % PRESET_COVERS.length]!.url;
}
