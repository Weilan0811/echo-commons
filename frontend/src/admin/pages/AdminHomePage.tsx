import { useLiveStatus, useReadyStatus } from '@/api/health';
import { ErrorNotice, Panel, StatusDot } from '@/components/ErrorNotice';

/**
 * 运行概况：管理员端首页。
 * 只展示当前已有的运行事实；对象发现、任务与追踪查询待管理契约确定后建设。
 */
export function AdminHomePage() {
  const live = useLiveStatus();
  const ready = useReadyStatus();

  return (
    <div className="flex flex-col gap-4">
      <Panel title="运行状态" description="进程存活与数据库就绪情况">
        {live.isError ? (
          <ErrorNotice error={live.error} onRetry={() => void live.refetch()} />
        ) : null}
        {ready.isError ? (
          <ErrorNotice error={ready.error} onRetry={() => void ready.refetch()} />
        ) : null}
        {live.isSuccess ? (
          <p className="text-sm">
            服务 {live.data.service} 版本 {live.data.version}
          </p>
        ) : null}
        {ready.isSuccess ? (
          <div className="mt-2 flex flex-col gap-1 text-sm text-content-muted">
            <StatusDot
              tone={ready.data.status === 'ready' ? 'ok' : 'warn'}
              label={`就绪：${ready.data.status}`}
            />
            <span>
              数据库{ready.data.database ? '就绪' : '不可用'}；后台工作
              {ready.data.workers_enabled ? `启用（${Object.keys(ready.data.workers).length} 个进程）` : '关闭'}
            </span>
          </div>
        ) : null}
      </Panel>

      <Panel title="尚未建设" description="以下内容需要先确定管理契约">
        <ul className="list-disc space-y-1 pl-5 text-sm text-content-muted">
          <li>社群、玩家、角色、会话、消息、轮次与任务的定位查询</li>
          <li>冻结输入、执行追踪与失败原因</li>
          <li>反思节点与结果</li>
          <li>材料封段与重新启动等操作</li>
        </ul>
        <p className="mt-3 text-xs text-content-muted">
          当前后端只提供部分列表、健康检查，以及按已知身份查询的上下文、反思与追踪接口，
          因此本页不显示这些内容，也不提供虚假数据。
        </p>
      </Panel>
    </div>
  );
}