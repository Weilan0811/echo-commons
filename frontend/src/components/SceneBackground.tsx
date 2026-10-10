/**
 * 场景背景层。
 *
 * 全玩家端固铺同一张暖夜插画：宽屏用 3840×2160 横版，窄窗用其中心裁出的
 * 竖版，不单独重绘。背景只负责氛围，因此再压两层遮罩——整体暗化与中部
 * 径向加深，保证消息阅读区与玻璃面板下的画面始终是暗且干净的，暖光只从
 * 边缘漏进来。
 *
 * 背景不响应交互，也不随页面切换重挂载，固定在视口上即可。
 */
export function SceneBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <picture className="absolute inset-0">
        <source media="(max-width: 900px)" srcSet="/assets/backgrounds/night-mobile.webp" />
        <img
          src="/assets/backgrounds/night-desktop.webp"
          alt=""
          className="size-full object-cover"
        />
      </picture>
      {/* 整体压暗：顶底略深，中间留出一线氛围。 */}
      <div
        className="absolute inset-0"
        style={{
            background:
              'linear-gradient(180deg, rgba(16,13,22,.5), rgba(16,13,22,.24) 42%, rgba(16,13,22,.54))',
          }}
        />
        {/* 中央加深：最亮处不允许落在阅读区。 */}
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse 72% 62% at 50% 42%, rgba(13,10,19,.62), transparent 72%)',
          }}
      />
    </div>
  );
}
