import { accentColor, avatarColors } from '@/lib/characterColor';

type AvatarSize = 'xs' | 'sm' | 'md' | 'lg';

const SIZE_CLASS: Record<AvatarSize, string> = {
  xs: 'size-4 text-[9px]',
  sm: 'size-6 text-[11px]',
  md: 'size-8 text-xs',
  lg: 'size-12 text-sm',
};

interface CharacterAvatarProps {
  /** 稳定标识。角色用 character_id，玩家用 player_id。 */
  readonly identity: string;
  readonly name: string;
  readonly size?: AvatarSize;
  /**
   * 图片地址。人物模板提供该字段时渲染图片，否则回退为底色加首字。
   * 契约中的头像字段可空，因此这里同时接受 undefined 与 null。
   */
  readonly imageUrl?: string | null | undefined;
  /** 图片加载失败时回退。 */
  readonly onImageError?: () => void;
}

/**
 * 角色头像。
 *
 * 配色由标识派生，因此同一角色在气泡、提及与棋子标记中始终同色。
 * 首字取显示名首个非空白字符；中文取第一个字，英文取首字母。
 */
export function CharacterAvatar({
  identity,
  name,
  size = 'md',
  imageUrl,
  onImageError,
}: CharacterAvatarProps) {
  const sizeClass = SIZE_CLASS[size];

  if (imageUrl !== undefined && imageUrl !== null && imageUrl !== '') {
    return (
      <img
        src={imageUrl}
        alt={name}
        onError={onImageError}
        className={`${sizeClass} shrink-0 rounded-full object-cover`}
      />
    );
  }

  const colors = avatarColors(identity);
  const initial = firstGlyph(name);

  return (
    <span
      className={`${sizeClass} flex shrink-0 items-center justify-center rounded-full font-medium`}
      style={{ backgroundColor: colors.background, color: colors.foreground }}
      aria-hidden="true"
    >
      {initial}
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
