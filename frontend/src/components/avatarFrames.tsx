import type { ReactElement, SVGProps } from 'react';

/**
 * 无肖像角色的装饰头像模板（抽象叙事元素，不出现具体人脸）。
 *
 * 模板内联为 React 组件而不是 <img>：所有笔触用 currentColor，颜色由
 * CharacterAvatar 按角色派生色在外部设置。中央留出区域放角色首字。
 * 与 public/assets/avatar-frames 下的交付素材保持同构。
 */

type FrameProps = SVGProps<SVGSVGElement>;

function Track() {
  // 四个模板共用的细虚线轨道圈，把不同母题收进同一形状语言。
  return (
    <circle
      cx="256"
      cy="256"
      r="204"
      stroke="currentColor"
      strokeWidth="3"
      strokeDasharray="2 14"
      opacity=".2"
    />
  );
}

function BranchFrame(props: FrameProps) {
  return (
    <svg viewBox="0 0 512 512" fill="none" aria-hidden="true" {...props}>
      <Track />
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
        <path
          d="M118 402c57-45 98-98 128-159 26-53 62-101 128-139"
          strokeWidth="12"
        />
        <path
          d="M176 351c-34 3-62-9-83-37 37-16 70-9 95 18M211 292c-34-8-56-29-66-63 39-4 69 13 85 47M251 232c-12-33-7-64 15-94 27 30 35 62 23 96M295 180c21-29 52-44 89-41-9 38-34 62-73 72M146 376c-20 26-48 40-84 40 10-36 34-59 69-68M345 141c11-34 34-57 70-68 2 39-17 67-55 83"
          strokeWidth="8"
        />
        <path
          d="M176 351c-34 3-62-9-83-37 37-16 70-9 95 18ZM211 292c-34-8-56-29-66-63 39-4 69 13 85 47ZM251 232c-12-33-7-64 15-94 27 30 35 62 23 96ZM295 180c21-29 52-44 89-41-9 38-34 62-73 72ZM146 376c-20 26-48 40-84 40 10-36 34-59 69-68"
          fill="currentColor"
          fillOpacity=".11"
          strokeWidth="6"
        />
      </g>
      <circle cx="414" cy="68" r="7" fill="currentColor" />
      <circle cx="78" cy="418" r="5" fill="currentColor" />
    </svg>
  );
}

function CrescentFrame(props: FrameProps) {
  return (
    <svg viewBox="0 0 512 512" fill="none" aria-hidden="true" {...props}>
      <Track />
      <path
        d="M322 102a151 151 0 1 0 91 276A174 174 0 0 1 322 102Z"
        fill="currentColor"
        fillOpacity=".13"
        stroke="currentColor"
        strokeWidth="10"
        strokeLinejoin="round"
      />
      <path
        d="M322 102a151 151 0 1 0 91 276A174 174 0 0 1 322 102Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        opacity=".55"
      />
      <path
        d="M352 112c17 21 29 46 35 73"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
        opacity=".48"
      />
      <path
        d="m383 182 9 21 23 2-18 15 5 22-19-12-20 11 7-22-17-16 22-1 8-20ZM149 239l7 16 18 2-14 12 4 18-16-9-16 9 4-18-13-12 18-2 8-16ZM340 314l5 12 14 1-11 9 3 14-12-7-13 7 4-14-11-9 14-1 7-12Z"
        fill="currentColor"
      />
      <circle cx="251" cy="382" r="5" fill="currentColor" opacity=".7" />
      <circle cx="287" cy="391" r="3" fill="currentColor" opacity=".55" />
    </svg>
  );
}

function WindowLightFrame(props: FrameProps) {
  return (
    <svg viewBox="0 0 512 512" fill="none" aria-hidden="true" {...props}>
      <Track />
      <path
        d="M148 348V211c0-60 48-108 108-108s108 48 108 108v137"
        stroke="currentColor"
        strokeWidth="13"
        strokeLinecap="round"
      />
      <path
        d="M173 342V212c0-46 37-83 83-83s83 37 83 83v130"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
      />
      <path
        d="M256 132v205M178 211h156"
        stroke="currentColor"
        strokeWidth="8"
        strokeLinecap="round"
      />
      <path d="M190 226h53v96h-53z" fill="currentColor" opacity=".16" />
      <path
        d="M193 374h126M216 401h80"
        stroke="currentColor"
        strokeWidth="11"
        strokeLinecap="round"
      />
      <path
        d="M120 155c18-23 42-42 70-54M392 155c-18-23-42-42-70-54"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
        opacity=".55"
      />
    </svg>
  );
}

function PaperPlaneFrame(props: FrameProps) {
  // 素材原画布为 128 且图形满幅，缩到右上区域，给中央首字留白。
  return (
    <svg viewBox="0 0 512 512" fill="none" aria-hidden="true" {...props}>
      <Track />
      <g transform="translate(286,72) scale(1.7)">
        <path
          d="M15 58.5 111 17 76 111 58 72 15 58.5Z"
          fill="currentColor"
          fillOpacity=".12"
          stroke="currentColor"
          strokeWidth="5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="m15 58.5 96-41.5-53 55"
          stroke="currentColor"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="m58 72 18 39 9-57"
          stroke="currentColor"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}

export interface AvatarFrame {
  readonly id: string;
  readonly Component: (props: FrameProps) => ReactElement;
}

export const AVATAR_FRAMES: ReadonlyArray<AvatarFrame> = [
  { id: 'branch', Component: BranchFrame },
  { id: 'crescent', Component: CrescentFrame },
  { id: 'window-light', Component: WindowLightFrame },
  { id: 'paperplane', Component: PaperPlaneFrame },
];

/** 由稳定标识挑一个模板：同一角色永远拿到同一母题。 */
export function pickAvatarFrame(identity: string): AvatarFrame {
  let hash = 0;
  for (let index = 0; index < identity.length; index += 1) {
    hash = (hash * 31 + identity.charCodeAt(index)) >>> 0;
  }
  return AVATAR_FRAMES[hash % AVATAR_FRAMES.length]!;
}
