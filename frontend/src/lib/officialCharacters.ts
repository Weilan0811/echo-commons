/**
 * 官方蓝图角色的随包素材注册。
 *
 * 后端地址优先。没有地址时按蓝图编号或官方名称选择随包素材，
 * 自定义角色没有素材时显示装饰头像。
 */
import { imageUrl } from '@/api/assets';

export interface OfficialCharacterAsset {
  readonly blueprintId: string;
  /** 官方中文名等精确名称，用于聊天成员这种只有 display_name 的场景。 */
  readonly names: readonly string[];
  readonly avatar: string;
  readonly illustration: string;
}

export const OFFICIAL_CHARACTERS: ReadonlyArray<OfficialCharacterAsset> = [
  {
    blueprintId: 'xiaojin',
    names: ['小槿'],
    avatar: '/assets/characters/xiaojin/avatar.png',
    illustration: '/assets/characters/xiaojin/illustration.png',
  },
];

/**
 * 解析角色头像。优先用服务端地址；否则按 blueprint_id、再按显示名匹配
 * 官方随包素材；都不命中返回 null，由头像组件回退到装饰模板。
 */
export function resolveOfficialAvatar(input: {
  readonly avatarUrl?: string | null | undefined;
  readonly blueprintId?: string | null | undefined;
  readonly displayName?: string | null | undefined;
}): string | null {
  if (input.avatarUrl !== undefined && input.avatarUrl !== null && input.avatarUrl !== '') {
    return imageUrl(input.avatarUrl);
  }
  if (input.blueprintId) {
    const byId = OFFICIAL_CHARACTERS.find((item) => item.blueprintId === input.blueprintId);
    if (byId !== undefined) return byId.avatar;
  }
  if (input.displayName) {
    const byName = OFFICIAL_CHARACTERS.find((item) => item.names.includes(input.displayName!));
    if (byName !== undefined) return byName.avatar;
  }
  return null;
}

/** 解析官方角色竖版插画，用于角色卡与创作预览；非官方角色返回 null。 */
export function resolveOfficialIllustration(input: {
  readonly illustrationUrl?: string | null | undefined;
  readonly blueprintId?: string | null | undefined;
  readonly displayName?: string | null | undefined;
}): string | null {
  if (input.illustrationUrl) return imageUrl(input.illustrationUrl);
  if (input.blueprintId) {
    const byId = OFFICIAL_CHARACTERS.find((item) => item.blueprintId === input.blueprintId);
    if (byId !== undefined) return byId.illustration;
  }
  if (input.displayName) {
    const byName = OFFICIAL_CHARACTERS.find((item) => item.names.includes(input.displayName!));
    if (byName !== undefined) return byName.illustration;
  }
  return null;
}
