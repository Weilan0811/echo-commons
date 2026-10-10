import { apiBaseUrl } from '@/api/http';

/** 社群封面预设随前端发布，选择保存在后端。 */
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

export function resolveCover(_seed: string | null | undefined, _name?: string | null,
  kind?: string | null, reference?: string | null): string | null {
  if (!reference) return null;
  if (kind === 'preset') return PRESET_COVERS.find((cover) => cover.id === reference)?.url ?? null;
  if (kind === 'asset') return new URL(`/api/assets/${encodeURIComponent(reference)}/images/standard`, apiBaseUrl()).href;
  return null;
}
