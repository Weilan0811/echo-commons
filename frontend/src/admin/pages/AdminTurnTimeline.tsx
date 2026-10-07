import { useState } from 'react';
import {
  AdminListState,
  AdminTable,
  FieldRow,
  MonoCell,
  PrivateText,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import {
  useAdminMessage,
  useAdminMessages,
  useAdminTask,
  useAdminTasks,
  useAdminTurn,
  type AdminTask,
  type AdminTaskDetail,
  type AdminMessageDetail,
} from '@/api/admin';
import { AgentSteps } from './AdminAgentSteps';

/**
 * 一次执行的链路。
 *
 * 一次玩家输入触发一个轮次，轮次决定谁来回应，回应各自建立任务，任务产出经过
 * 审核才成为消息。这几件事分散在会话、任务与消息三处，排障时必须来回跳。
 * 这里按发生顺序串成一条：输入、受众、选择、任务、提交。
 *
 * 每一步都是可选展开的：链路本身已经说明顺序，只有需要看具体内容时才深入。
 */
export function TurnTimeline({
  communityId,
  conversationId,
  turnId,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly turnId: string;
}) {
  const turn = useAdminTurn(communityId, conversationId, turnId);
  const detail = turn.data;
  if (detail === undefined) {
    return (
      <AdminListState isPending={turn.isPending} error={turn.error} isEmpty={false} emptyText="">
        <p className="text-[12px] text-content-faint">正在读取轮次。</p>
      </AdminListState>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <Step title="输入" hint={detail.input_message_ids.length + ' 条'}>
        <InputMessages
          communityId={communityId}
          conversationId={conversationId}
          messageIds={detail.input_message_ids}
        />
      </Step>
      <Step title="受众" hint={detail.audience.length + ' 个成员区间'}>
        {/* audience 是成员区间编号，不是主体。编号对应会话详情里的成员区间表。 */}
        <div className="flex flex-wrap gap-1.5">
          {detail.audience.map((membershipId) => (
            <MonoCell key={membershipId}>{membershipId}</MonoCell>
          ))}
        </div>
      </Step>
      <Step title="选择" hint={summaryOf(detail.participation)}>
        <AdminTable
          headers={['角色', '原因', '次序', '状态', '结果']}
          rows={detail.participation.map((decision) => ({
            key: decision.character_id,
            cells: [
              <MonoCell key="c">{decision.character_id}</MonoCell>,
              <MonoCell key="r">{decision.reason_code}</MonoCell>,
              <MonoCell key="o">
                {decision.selection_order === null ? '—' : String(decision.selection_order)}
              </MonoCell>,
              <StatusBadge key="s" value={decision.status} />,
              <MonoCell key="u">{decision.outcome ?? '—'}</MonoCell>,
            ],
          }))}
        />
      </Step>
      <Step title="任务" hint={detail.task_ids.length + ' 个'}>
        <TurnTasks
          communityId={communityId}
          conversationId={conversationId}
          turnId={turnId}
          taskIds={detail.task_ids}
        />
      </Step>
      <Step title="提交" hint="本轮产生的消息">
        <SubmittedMessages
          communityId={communityId}
          conversationId={conversationId}
          turnId={turnId}
        />
      </Step>
    </div>
  );
}
/** 链路的一步。标题行显示数量或结论，内容按需展开。 */
function Step({
  title,
  hint,
  children,
}: {
  readonly title: string;
  readonly hint: string;
  readonly children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-2">
        <span className="text-[12px] text-content">{title}</span>
        <span className="text-[11px] text-content-faint">{hint}</span>
      </summary>
      {open ? <div className="mt-1.5 pl-1">{children}</div> : null}
    </details>
  );
}

/** 一句话概括选择结果：被选中几个、发言几个、沉默几个。 */
function summaryOf(
  decisions: ReadonlyArray<{ status: string; outcome: string | null }>,
): string {
  const selected = decisions.filter((item) => item.status !== 'silent').length;
  const spoke = decisions.filter((item) => item.outcome === 'message').length;
  const silent = decisions.filter((item) => item.outcome === 'silent').length;
  return selected + ' 个角色参与，' + spoke + ' 个发言，' + silent + ' 个沉默';
}

/** 输入消息。按轮次给出的编号读取，不从会话消息列表里筛。 */
function InputMessages({
  communityId,
  conversationId,
  messageIds,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly messageIds: readonly string[];
}) {
  if (messageIds.length === 0) return <p className="text-[12px] text-content-faint">这一轮没有输入。</p>;
  return (
    <div className="flex flex-col gap-1.5">
      {messageIds.map((id) => (
        <InputMessage key={id} communityId={communityId} conversationId={conversationId} id={id} />
      ))}
    </div>
  );
}

function InputMessage({
  communityId,
  conversationId,
  id,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly id: string;
}) {
  const message = useAdminMessage(communityId, conversationId, id);
  return (
    <AdminListState
      isPending={message.isPending}
      error={message.error}
      isEmpty={false}
      emptyText=""
    >
      {message.data === undefined ? null : (
        <div className="flex flex-col">
          <FieldRow label={'序号 ' + message.data.sequence}>
                        {senderLabel(message.data.sender)}
          </FieldRow>
          <PrivateText label="正文" text={message.data.text} />
        </div>
      )}
    </AdminListState>
  );
}
/**
 * 本轮的任务。
 *
 * 任务编号在轮次里给出，但按编号读取详情需要角色标识，而角色标识只能从任务
 * 列表取。因此先读该会话的任务列表筛出本轮的，再逐个展开详情。
 */
function TurnTasks({
  communityId,
  conversationId,
  turnId,
  taskIds,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly turnId: string;
  readonly taskIds: readonly string[];
}) {
  const list = useAdminTasks(communityId, { conversationId: conversationId ?? '', limit: 100 });
  if (taskIds.length === 0) {
    return <p className="text-[12px] text-content-faint">这一轮没有建立任务。</p>;
  }
  const mine = (list.data?.items ?? []).filter(
    (item) => item.social_turn_id === turnId && taskIds.includes(item.task_id),
  );
  if (list.isPending) return <p className="text-[12px] text-content-faint">正在读取任务列表。</p>;
  if (mine.length === 0) {
    return (
      <p className="text-[12px] text-content-faint">
        任务列表里没有本轮的记录，可能已被清理或超出列表范围。
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      {mine.map((task) => (
        <TaskCard key={task.task_id} communityId={communityId} task={task} />
      ))}
    </div>
  );
}

/** 任务卡：概要常显，冻结上下文与审核结果按需展开。 */
function TaskCard({
  communityId,
  task,
}: {
  readonly communityId: string | null;
  readonly task: AdminTask;
}) {
  const [open, setOpen] = useState(false);
  const detail = useAdminTask(communityId, task.character_id, open ? task.task_id : null);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-2">
        <span className="tabular text-[11px] text-content-faint">{task.task_id}</span>
        <StatusBadge value={task.status} />
        <span className="ml-auto text-[11px] text-content-faint">
          第 {task.attempt_count} 次尝试
        </span>
      </summary>
      {open ? (
        <div className="mt-1.5 flex flex-col gap-2 pl-1">
          <AdminListState
            isPending={detail.isPending}
            error={detail.error}
            isEmpty={false}
            emptyText=""
          >
            {detail.data === undefined ? null : <TaskOutcome detail={detail.data} />}
          </AdminListState>
        </div>
      ) : null}
    </details>
  );
}
/** 任务结果：逐步执行、产物、审核与恢复历史。 */
function TaskOutcome({ detail }: { readonly detail: AdminTaskDetail }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col">
        <FieldRow label="角色">{detail.task.character_id}</FieldRow>
        <FieldRow label="状态">
          <StatusBadge value={detail.task.status} />
        </FieldRow>
        <FieldRow label="尝试次数">{detail.task.attempt_count}</FieldRow>
        <FieldRow label="最近失败">
          {detail.task.last_failure === null || detail.task.last_failure === undefined
            ? '—'
            : detail.task.last_failure.code}
        </FieldRow>
        <FieldRow label="最近恢复动作">{detail.task.last_recovery_action ?? '—'}</FieldRow>
      </div>

      {detail.results.length === 0 ? (
        <p className="text-[12px] text-content-faint">还没有审核结果。</p>
      ) : (
        detail.results.map((result) => (
          <div key={result.result_id} className="flex flex-col gap-1.5">
            <span className="text-[11px] text-content-faint">
              第 {result.attempt_no} 次尝试，审核 {result.status}
              {result.decision_code === null ? '' : '（' + result.decision_code + '）'}
            </span>
            {result.payload.status === 'completed' ? (
              <>
                <PrivateText
                  label="发言"
                  text={result.payload.output.payload.utterance}
                />
                <PrivateText
                  label="内心记录"
                  text={result.payload.output.payload.thought}
                  removed={result.thought_removed_at_utc !== null}
                />
                {result.payload.steps.length > 0 ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-[11px] text-content-faint">逐步执行</span>
                    <AgentSteps
                      steps={result.payload.steps}
                      usage={result.payload.usage_summary}
                    />
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-[12px] text-content-faint">模型没有提出发言。</p>
            )}
          </div>
        ))
      )}

      {detail.context === null || detail.context === undefined ? null : (
        <PrivateText
          label="冻结上下文"
          text={JSON.stringify(detail.context, null, 2)}
        />
      )}

      <RecoveryList items={detail.recovery_history.items} />
    </div>
  );
}

/** 恢复事件按时间列出，事件名直接用后端枚举。 */
function RecoveryList({
  items,
}: {
  readonly items: AdminTaskDetail['recovery_history']['items'];
}) {
  if (items.length === 0) {
    return <p className="text-[12px] text-content-faint">没有恢复事件。</p>;
  }
  return (
    <AdminTable
      headers={['事件', '尝试', '记录时间']}
      rows={items.map((item) => ({
        key: String(item.event_id),
        cells: [
          <MonoCell key="e">{item.event_kind}</MonoCell>,
          <MonoCell key="a">{String(item.attempt)}</MonoCell>,
          <TimeCell key="t" value={item.recorded_at_utc} />,
        ],
      }))}
    />
  );
}
/**
 * 本轮提交的消息。
 *
 * 消息列表按序号返回，来源轮次在每条消息上，因此按序号倒着读，直到找到本轮的
 * 消息或到达已加载的边界。找不到时说明页面内没有这条记录，而不是本轮没有产出。
 */
function SubmittedMessages({
  communityId,
  conversationId,
  turnId,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly turnId: string;
}) {
  const [open, setOpen] = useState(false);
  const messages = useAdminMessages(
    open ? communityId : null,
    open ? conversationId : null,
    { limit: 50 },
  );
  const items = messages.data?.items ?? [];
  const mine = items.filter((item) => item.source_turn_id === turnId);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-2">
        <span className="text-[12px] text-content">已加载范围内</span>
        <span className="text-[11px] text-content-faint">
          {open ? mine.length + ' 条来自本轮' : '按需读取'}
        </span>
      </summary>
      {open ? (
        <AdminListState
          isPending={messages.isPending}
          error={messages.error}
          isEmpty={mine.length === 0}
          emptyText="最近五十条里没有本轮产生的消息。它可能更早，需要在消息列表里按序号查找。"
        >
          <div className="flex flex-col gap-1.5">
            {mine.map((item) => (
              <div key={item.message_id} className="flex flex-col">
                <FieldRow label={'序号 ' + item.sequence}>
                  {item.sender_kind}:{item.sender_id}
                </FieldRow>
                <PrivateText label="正文" text={item.text_preview} />
              </div>
            ))}
          </div>
        </AdminListState>
      ) : null}
    </details>
  );
}

/** 发送者标签。系统消息没有 actor_id，它用 source_id 标识来源类别。 */
function senderLabel(sender: AdminMessageDetail['sender']): string {
  if (sender.kind === 'system') return 'system:' + sender.source_id;
  return sender.kind + ':' + sender.actor_id;
}
