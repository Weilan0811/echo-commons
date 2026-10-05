import { Shell } from '@/components/Shell';
import { EmptyState } from '@/components/EmptyState';

/**
 * 游戏列表。
 *
 * 活动模块尚未实现，这里显示空状态而不是占位卡片：未接入的功能不显示为
 * 可用入口。阶段五接入后由服务端活动列表替换，见 docs/03-page-design.md 第 8 节。
 */
export function GamesPage() {
  return (
    <Shell section="games" list={null}>
      <EmptyState
        title="还没有可玩的玩法"
        description="活动模块尚未实现。四人飞行棋作为首个接入场景，接口与玩法规则在后端活动设计确定后接入。"
      />
    </Shell>
  );
}
