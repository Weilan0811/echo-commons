import { useParams } from 'react-router';
import {
  AdminPage,
  AdminListState,
  AdminSection,
  FieldRow,
  MonoCell,
  PrivateText,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import { useAdminTask, useAdminTaskContext, useAdminTrace } from '@/api/admin';

/**
 * 任务诊断。
 *
 * 任务详情是排障的终点：冻结输入、每次审核结果与恢复历史都在这里。私有正文
 * 默认折叠——它通常很长，而排障时往往先看状态与最近失败。
 */
export function AdminTaskPage() {
  const params = useParams();
  const communityId = params.communityId ?? null;
  const characterId = params.characterId ?? null;
  const taskId = params.taskId ?? null;

  const task = useAdminTask(communityId, characterId, taskId);
  const context = useAdminTaskContext(communityId, characterId, taskId);
  const trace = useAdminTrace(communityId, task.data?.task.trace_id ?? null, characterId);

  return (
    <AdminPage
      title={taskId ?? '任务'}
      subtitle="冻结输入、审核结果与恢复历史。上下文是私有正文，只在任务范围内可见。"
    >
      <AdminSection title="任务">
        <AdminListState isPending={task.isPending} error={task.error} isEmpty={false} emptyText="">
          <div className="flex flex-col">
            <FieldRow label="任务">{task.data?.task.task_id}</FieldRow>
            <FieldRow label="会话">{task.data?.task.conversation_id}</FieldRow>
            <FieldRow label="轮次">{task.data?.task.social_turn_id ?? '—'}</FieldRow>
            <FieldRow label="状态">
              {task.data === undefined ? null : <StatusBadge value={task.data.task.status} />}
            </FieldRow>
            <FieldRow label="尝试次数">{task.data?.task.attempt_count}</FieldRow>
            <FieldRow label="租约代次">{task.data?.task.lease_generation}</FieldRow>
            <FieldRow label="成员区间">{task.data?.task.conversation_id ?? '—'}</FieldRow>
            <FieldRow label="最近失败">
              {task.data?.task.last_failure == null ? '—' : task.data.task.last_failure.code}
            </FieldRow>
            <FieldRow label="最近恢复动作">
              {task.data?.task.last_recovery_action ?? '—'}
            </FieldRow>
            <FieldRow label="下次尝试">
              <TimeCell value={task.data?.task.next_attempt_at_utc} />
            </FieldRow>
            <FieldRow label="次数耗尽">
              {task.data?.task.retry_exhausted === true ? '是' : '否'}
            </FieldRow>
            <FieldRow label="创建时间">
              <TimeCell value={task.data?.task.created_at_utc} />
            </FieldRow>
          </div>
        </AdminListState>
      </AdminSection>

      <AdminSection title="审核结果">
        <AdminListState
          isPending={task.isPending}
          error={task.error}
          isEmpty={(task.data?.results.length ?? 0) === 0}
          emptyText="还没有审核结果。"
        >
          <ul className="flex flex-col gap-1">
            {(task.data?.results ?? []).map((result) => (
              <li key={result.result_id} className="border-t border-border-subtle/60 py-1.5">
                <div className="flex items-baseline gap-3">
                  <MonoCell>{result.decision_code}</MonoCell>
                  <TimeCell value={result.decided_at_utc} />
                </div>
                {result.payload.status === 'completed' ? (
                  <>
                    <PrivateText label="发言" text={result.payload.output.payload.utterance} />
                    <PrivateText
                      label="内心记录"
                      text={result.payload.output.payload.thought}
                      removed={result.thought_removed_at_utc !== null}
                    />
                    {result.thought_removed_at_utc !== null ? (
                      <FieldRow label="内心清除时间">
                        <TimeCell value={result.thought_removed_at_utc} />
                      </FieldRow>
                    ) : null}
                  </>
                ) : (
                  <p className="text-xs text-content-faint">角色选择沉默。</p>
                )}
                <PrivateText label="运行详情" text={JSON.stringify(result.payload, null, 2)} />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection title="恢复历史" count={task.data?.recovery_history.items.length ?? 0}>
        <AdminListState
          isPending={task.isPending}
          error={task.error}
          isEmpty={(task.data?.recovery_history.items.length ?? 0) === 0}
          emptyText="没有恢复事件。"
        >
          <ul className="flex flex-col gap-1">
            {(task.data?.recovery_history.items ?? []).map((event) => (
              <li key={event.event_id} className="border-t border-border-subtle/60 py-1.5">
                <div className="flex items-baseline gap-3">
                  <MonoCell>{event.event_kind}</MonoCell>
                  <TimeCell value={event.recorded_at_utc} />
                </div>
                <PrivateText label="载荷" text={JSON.stringify(event.payload, null, 2)} />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection title="冻结上下文">
        <AdminListState
          isPending={context.isPending}
          error={context.error}
          isEmpty={false}
          emptyText=""
        >
          <div className="flex flex-col">
            <FieldRow label="快照">{context.data?.snapshot_id}</FieldRow>
            <FieldRow label="准备时间">
              <TimeCell value={context.data?.prepared_at_utc} />
            </FieldRow>
            <FieldRow label="提示布局版本">{context.data?.prompt_layout_version}</FieldRow>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            <PrivateText
              label="自我"
              text={JSON.stringify(context.data?.self ?? null, null, 2)}
            />
            <PrivateText
              label="视角"
              text={JSON.stringify(context.data?.perspective ?? null, null, 2)}
            />
            <PrivateText
              label="记忆"
              text={JSON.stringify(context.data?.memory ?? null, null, 2)}
            />
            <PrivateText
              label="环境"
              text={JSON.stringify(context.data?.environment ?? null, null, 2)}
            />
          </div>
        </AdminListState>
      </AdminSection>

      <AdminSection title="追踪">
        <AdminListState isPending={trace.isPending} error={trace.error} isEmpty={false} emptyText="">
          <PrivateText
            label={task.data?.task.trace_id ?? '追踪'}
            text={JSON.stringify(trace.data?.traces ?? null, null, 2)}
          />
        </AdminListState>
      </AdminSection>
    </AdminPage>
  );
}
