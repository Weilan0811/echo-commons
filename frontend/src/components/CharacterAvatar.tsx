import { accentColor, avatarColors } from '@/lib/characterColor';
import { pickAvatarFrame } from './avatarFrames';
import { useState } from 'react';
import { imageUrl as resolveImageUrl } from '@/api/assets';

type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

const SIZE_CLASS: Record<AvatarSize, string> = {
  xs: 'size-4 text-[9px]',
  sm: 'size-9 text-[12px]',
  md: 'size-10 text-xs',
  lg: 'size-14 text-base',
  xl: 'size-20 text-2xl',
};

/** 该尺寸及以上才画装饰母题；再小母题细节会糊成一团，只留首字。 */
const FRAME_MIN_SIZE: AvatarSize = 'md';
const SIZE_ORDER: ReadonlyArray<AvatarSize> = ['xs', 'sm', 'md', 'lg', 'xl'];

interface CharacterAvatarProps {
  /** 稳定标识。角色用 character_id，玩家用 player_id。 */
  readonly identity: string;
  readonly name: string;
  readonly size?: AvatarSize;
  /**
   * 图片地址。有人物模板提供该字段时渲染真实肖像，否则回退为装饰模板加
   * 首字。契约中的头像字段可空，因此这里同时接受 undefined 与 null。
   */
  readonly imageUrl?: string | null | undefined;
  /** 图片加载失败时回退。 */
  readonly onImageError?: () => void;
  /**
   * 是否加角色色光环。
   *
   * 光环让角色在深色背景上有实体感，主要用在消息头像与角色卡片这类需要
   * 一眼分辨的位置；列表里的小头像不加，否则整屏都是圈。
   */
  readonly glow?: boolean;
}

/**
 * 角色头像。
 *
 * 三层回退：真实肖像图 → 抽象装饰模板（按 identity 稳定选择母题，按角色
 * 派生色着色，中央放首字）→ 过小尺寸只留首字圆底。配色由标识派生，因此
 * 同一角色在气泡、提及与棋子标记中始终同色。
 */
export function CharacterAvatar({
  identity,
  name,
  size = 'md',
  imageUrl,
  onImageError,
  glow = false,
}: CharacterAvatarProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const sizeClass = SIZE_CLASS[size];
  const ring = glow ? ' avatar-glow' : '';

  if (imageUrl !== undefined && imageUrl !== null && imageUrl !== '' && failedUrl !== imageUrl) {
    return (
      <img
        src={resolveImageUrl(imageUrl)}
        alt={name}
        onError={() => { setFailedUrl(imageUrl); onImageError?.(); }}
        className={`${sizeClass}${ring} shrink-0 rounded-full object-cover`}
        style={{ color: accentColor(identity) }}
      />
    );
  }

  const colors = avatarColors(identity);
  const initial = firstGlyph(name);
  const showFrame = SIZE_ORDER.indexOf(size) >= SIZE_ORDER.indexOf(FRAME_MIN_SIZE);
  const frame = showFrame ? pickAvatarFrame(identity) : null;
  const FrameComponent = frame?.Component;

  return (
    <span
      className={`${sizeClass}${ring} relative flex shrink-0 items-center justify-center overflow-hidden rounded-full font-medium`}
      style={{
        color: colors.foreground,
        backgroundColor: `color-mix(in oklch, ${colors.background} 72%, var(--color-surface-overlay))`,
      }}
      aria-hidden="true"
    >
      {FrameComponent !== undefined ? (
        <FrameComponent className="absolute inset-0 size-full p-[3px]" />
      ) : null}
      {initial !== '' ? (
        <span className="relative leading-none">{initial}</span>
      ) : null}
    </span>
  );
}

/** 首字。显示名为空或全空白时返回空字符串，不显示占位文字。 */
function firstGlyph(name: string): string {
  for (const character of name.trim()) {
    return character;
  }
  return '';
}

/** 角色名或提及高亮使用的强调色。 */
export function CharacterName({
  identity,
  children,
  className = '',
}: {
  readonly identity: string;
  readonly children: string;
  readonly className?: string;
}) {
  return (
    <span className={className} style={{ color: accentColor(identity) }}>
      {children}
    </span>
  );
}
