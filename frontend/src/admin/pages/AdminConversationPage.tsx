import { useParams } from 'react-router';
import {
  AdminPage,
  AdminDisclosure,
  AdminListState,
  AdminSection,
  AdminTable,
  FieldRow,
  MonoCell,
  PrivateText,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import { TurnTimeline } from './AdminTurnTimeline';
import { AdminGamePanel } from './AdminGamePanel';
import {
  useAdminConversation,
  useAdminIntervals,
  useAdminMessage,
  useAdminMessages,
  useAdminTrace,
  useAdminTurn,
  useAdminTurns,
  type AdminMessageDetail,
} from '@/api/admin';

/**
 * 会话诊断。
 *
 * 消息、轮次、成员区间三类事实并列。消息详情与轮次详情按需展开：它们包含
 * 私有正文与追踪编号，默认全部读出来会让这一屏没法看。
 */
export function AdminConversationPage() {
  const params = useParams();
  const communityId = params.communityId ?? null;
  const conversationId = params.conversationId ?? null;
  const conversation = useAdminConversation(communityId, conversationId);
  const messages = useAdminMessages(communityId, conversationId, { limit: 50 });
  const turns = useAdminTurns(communityId, conversationId, { limit: 30 });
  const intervals = useAdminIntervals(communityId, conversationId, { limit: 50 });

  const messageItems = messages.data?.items ?? [];
  const turnItems = turns.data?.items ?? [];
  const intervalItems = intervals.data?.items ?? [];

  return (
    <AdminPage
      title={conversationId ?? '会话'}
      subtitle="消息、轮次与成员区间。这里能看到玩家端看不到的历史私有消息。"
    >
      <AdminSection title="会话详情">
        <AdminListState
          isPending={conversation.isPending}
          error={conversation.error}
          isEmpty={false}
          emptyText=""
        >
          <div className="flex flex-col">
            <FieldRow label="标识">{conversation.data?.conversation_id}</FieldRow>
            <FieldRow label="类型">{conversation.data?.kind}</FieldRow>
            <FieldRow label="状态">
              {conversation.data === undefined ? null : (
                <StatusBadge value={conversation.data.status} />
              )}
            </FieldRow>
            <FieldRow label="下一序号">{conversation.data?.next_sequence}</FieldRow>
          </div>
        </AdminListState>
      </AdminSection>

      {conversation.data?.kind === 'game' && communityId && conversationId ? (
        <AdminGamePanel
          key={conversationId}
          communityId={communityId}
          conversationId={conversationId}
        />
      ) : null}

      <AdminSection title="消息" count={messageItems.length}>
        <AdminListState
          isPending={messages.isPending}
          error={messages.error}
          isEmpty={messageItems.length === 0}
          emptyText="没有消息。"
        >
          <ul className="flex flex-col gap-1">
            {messageItems.map((message) => (
              <li key={message.message_id} className="border-t border-border-subtle/60 py-1.5">
                <MessageRow
                  communityId={communityId}
                  conversationId={conversationId}
                  messageId={message.message_id}
                  sequence={message.sequence}
                  senderKind={message.sender_kind}
                  senderId={message.sender_id}
                  preview={message.text_preview}
                  visibility={message.visibility}
                  traceId={message.trace_id}
                />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection title="轮次" count={turnItems.length}>
        <AdminListState
          isPending={turns.isPending}
          error={turns.error}
          isEmpty={turnItems.length === 0}
          emptyText="没有轮次。"
        >
          <ul className="flex flex-col">
            {turnItems.map((turn) => (
              <li key={turn.social_turn_id} className="border-t border-border-subtle/60 py-1">
                <AdminDisclosure
                  summary={
                    <>
                      <span className="tabular text-[12px] text-content">
                        轮次 {turn.social_turn_id.slice(0, 8)}
                      </span>
                      <StatusBadge value={turn.status} />
                      <span className="ml-auto flex items-baseline gap-2">
                        <span className="text-[11px] text-content-faint">
                          观察上限 {turn.observation_max_sequence}
                        </span>
                        <TimeCell value={turn.completed_at_utc} />
                      </span>
                    </>
                  }
                >
                  <div className="mt-2 pl-1">
                    <TurnTimeline
                      communityId={communityId}
                      conversationId={conversationId}
                      turnId={turn.social_turn_id}
                    />
                  </div>
                </AdminDisclosure>
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection title="成员区间" count={intervalItems.length}>
        <AdminListState
          isPending={intervals.isPending}
          error={intervals.error}
          isEmpty={intervalItems.length === 0}
          emptyText="没有成员区间。"
        >
          <AdminTable
            headers={['标识', '类型', '加入后序号', '离开序号']}
            rows={intervalItems.map((interval) => ({
              key: interval.membership_id,
              cells: [
                <MonoCell key="i">{interval.actor_id}</MonoCell>,
                <MonoCell key="k">{interval.actor_kind}</MonoCell>,
                <MonoCell key="j">{String(interval.joined_after_sequence)}</MonoCell>,
                <MonoCell key="l">
                  {interval.left_at_sequence === null ? '—' : String(interval.left_at_sequence)}
                </MonoCell>,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>
    </AdminPage>
  );
}
/**
 * 消息行。
 *
 * 概要给序号、发送者、预览与可见范围；点开才读完整正文与来源结果。
 * 玩家消息用 message_id 与 trace_id 都能定位追踪，两种都留着。
 */
function MessageRow({
  communityId,
  conversationId,
  messageId,
  sequence,
  senderKind,
  senderId,
  preview,
  visibility,
  traceId,
}: {
  readonly communityId: string | null;
  readonly conversationId: string | null;
  readonly messageId: string;
  readonly sequence: number;
  readonly senderKind: string;
  readonly senderId: string;
  readonly preview: string;
  readonly visibility: string;
  readonly traceId: string;
}) {
  const detail = useAdminMessage(communityId, conversationId, messageId);
  const trace = useAdminTrace(
    communityId,
    detail.data?.trace_id ?? traceId,
    characterOf(detail.data?.sender),
  );

  return (
    <details>
      <summary className="flex cursor-pointer items-baseline gap-3">
        <span className="tabular w-10 shrink-0 text-[12px] text-content-faint">{sequence}</span>
        <span className="tabular w-28 shrink-0 truncate text-[12px] text-content-muted">
          {senderKind}:{senderId}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px]">{preview}</span>
        {visibility === 'recipients' ? (
          <span className="shrink-0 text-[10px] text-warn">私有</span>
        ) : null}
      </summary>

      <div className="mt-2 flex flex-col gap-2 pl-10">
        <AdminListState
          isPending={detail.isPending}
          error={detail.error}
          isEmpty={false}
          emptyText=""
        >
          <PrivateText label="完整正文" text={detail.data?.text} />
          <div className="flex flex-col">
            <FieldRow label="实际受众">
              {detail.data?.audience.map((member) => member.membership_id).join('、') ?? '—'}
            </FieldRow>
            <FieldRow label="来源轮次">{detail.data?.source_turn_id ?? '—'}</FieldRow>
            <FieldRow label="来源结果">{detail.data?.result_id ?? '—'}</FieldRow>
            <FieldRow label="时间">
              <TimeCell value={detail.data?.created_at_utc} />
            </FieldRow>
          </div>
        </AdminListState>

        <AdminListState
          isPending={trace.isPending}
          error={trace.error}
          isEmpty={false}
          emptyText=""
        >
          <PrivateText
            label={'追踪 ' + (detail.data?.trace_id ?? traceId)}
            text={JSON.stringify(trace.data?.traces ?? null, null, 2)}
          />
        </AdminListState>
      </div>
    </details>
  );
}

/**
 * 追踪查询要限定的角色。
 *
 * 只有角色消息才传角色标识：契约规定指定角色时只接受属于该角色的关联，
 * 玩家消息用玩家标识限定会返回 404。玩家消息按社群范围读取。
 */
function characterOf(sender: AdminMessageDetail['sender'] | undefined): string | null {
  return sender?.kind === 'character' ? sender.actor_id : null;
}
