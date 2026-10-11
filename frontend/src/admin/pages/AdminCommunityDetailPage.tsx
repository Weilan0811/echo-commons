import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { CommunityCleanup } from './CommunityCleanup';
import {
  AdminPage,
  AdminListState,
  AdminSection,
  AdminTable,
  FieldRow,
  MonoCell,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import {
  useAdminCharacters,
  useAdminCommunity,
  useAdminCommunityMembers,
  useAdminConversations,
  useAdminTasks,
} from '@/api/admin';

/**
 * 社群诊断。
 *
 * 一个页面里并列四类对象：角色、会话、任务与成员。它们都绑定社群范围，
 * 拆成四个页面会让排障时来回切换，而它们之间没有从属关系。
 */
export function AdminCommunityDetailPage() {
  const params = useParams();
  const communityId = params.communityId ?? null;
  const community = useAdminCommunity(communityId);
  const members = useAdminCommunityMembers(communityId, { limit: 50 });
  const characters = useAdminCharacters(communityId, { limit: 50 });
  const conversations = useAdminConversations(communityId, { limit: 50 });
  const [taskStatus, setTaskStatus] = useState('');
  const tasks = useAdminTasks(communityId, { limit: 30, status: taskStatus });

  const memberItems = members.data?.items ?? [];
  const characterItems = characters.data?.items ?? [];
  const conversationItems = conversations.data?.items ?? [];
  const taskItems = tasks.data?.items ?? [];
  const base = '/admin/communities/' + (communityId ?? '');

  return (
    <AdminPage
      title={community.data?.name ?? communityId ?? '社群'}
      subtitle="角色、会话、任务与成员都属于这个社群范围。"
    >
      <AdminSection title="社群详情">
        <AdminListState
          isPending={community.isPending}
          error={community.error}
          isEmpty={false}
          emptyText=""
        >
          <div className="flex flex-col">
            <FieldRow label="标识">{community.data?.community_id}</FieldRow>
            <FieldRow label="时区">{community.data?.timezone}</FieldRow>
            <FieldRow label="世界时间">
              <TimeCell value={community.data?.world_time_utc} />
            </FieldRow>
            <FieldRow label="状态">
              {community.data === undefined ? null : <StatusBadge value={community.data.status} />}
            </FieldRow>
            <FieldRow label="状态版本">{community.data?.state_version}</FieldRow>
          </div>
        </AdminListState>
      </AdminSection>

      {community.data ? <CommunityCleanup key={community.data.community_id}
        community={community.data} members={memberItems} /> : null}

      <AdminSection title="角色" count={characterItems.length}>
        <AdminListState
          isPending={characters.isPending}
          error={characters.error}
          isEmpty={characterItems.length === 0}
          emptyText="这个社群没有角色。"
        >
          <AdminTable
            headers={['名称', '标识', '模板', '可用性']}
            rows={characterItems.map((character) => ({
              key: character.character_id,
              cells: [
                <Link
                  key="n"
                  to={base + '/characters/' + character.character_id}
                  className="text-[13px] text-content hover:text-accent"
                >
                  {character.display_name}
                </Link>,
                <MonoCell key="i">{character.character_id}</MonoCell>,
                <MonoCell key="b">
                  {character.blueprint_id} v{character.blueprint_version}
                </MonoCell>,
                <StatusBadge key="s" value={character.availability_status} />,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>

      <AdminSection title="会话" count={conversationItems.length}>
        <AdminListState
          isPending={conversations.isPending}
          error={conversations.error}
          isEmpty={conversationItems.length === 0}
          emptyText="没有会话。"
        >
          <AdminTable
            headers={['标识', '类型', '状态', '成员版本']}
            rows={conversationItems.map((conversation) => ({
              key: conversation.conversation_id,
              cells: [
                <Link
                  key="i"
                  to={base + '/conversations/' + conversation.conversation_id}
                  className="tabular text-[13px] text-content hover:text-accent"
                >
                  {conversation.conversation_id}
                </Link>,
                <MonoCell key="k">{conversation.kind}</MonoCell>,
                <StatusBadge key="s" value={conversation.status} />,
                <MonoCell key="n">{String(conversation.membership_version)}</MonoCell>,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>
      <AdminSection
        title="任务"
        count={taskItems.length}
        actions={
          <select
            value={taskStatus}
            onChange={(event) => {
              setTaskStatus(event.target.value);
            }}
            className="rounded-md border border-border-subtle bg-surface-sunken px-2 py-1 text-[11px] outline-none"
          >
            <option value="">全部状态</option>
            {TASK_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        }
      >
        <AdminListState
          isPending={tasks.isPending}
          error={tasks.error}
          isEmpty={taskItems.length === 0}
          emptyText="没有任务。"
        >
          <AdminTable
            headers={['任务', '角色', '状态', '尝试', '下次尝试', '耗尽']}
            rows={taskItems.map((task) => ({
              key: task.task_id,
              cells: [
                <Link
                  key="i"
                  to={base + '/characters/' + task.character_id + '/tasks/' + task.task_id}
                  className="tabular text-[13px] text-content hover:text-accent"
                >
                  {task.task_id}
                </Link>,
                <MonoCell key="c">{task.character_id}</MonoCell>,
                <StatusBadge key="s" value={task.status} />,
                <MonoCell key="a">{String(task.attempt_count)}</MonoCell>,
                <TimeCell key="n" value={task.next_attempt_at_utc} />,
                <span key="e" className="text-[12px]">
                  {task.retry_exhausted === true ? (
                    <span className="text-danger">是</span>
                  ) : (
                    <span className="text-content-faint">否</span>
                  )}
                </span>,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>

      <AdminSection title="成员" count={memberItems.length}>
        <AdminListState
          isPending={members.isPending}
          error={members.error}
          isEmpty={memberItems.length === 0}
          emptyText="没有成员。"
        >
          <AdminTable
            headers={['标识', '类型', '加入时间']}
            rows={memberItems.map((member) => ({
              key: member.actor_id,
              cells: [
                <MonoCell key="i">{member.actor_id}</MonoCell>,
                <MonoCell key="k">{member.actor_kind}</MonoCell>,
                <TimeCell key="j" value={member.joined_at_utc} />,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>
    </AdminPage>
  );
}

const TASK_STATUSES = [
  'pending',
  'processing',
  'retry_wait',
  'suspended',
  'completed',
  'failed',
  'cancelled',
] as const;
