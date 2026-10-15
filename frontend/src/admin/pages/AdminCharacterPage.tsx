import { useState } from 'react';
import { ErrorNotice } from '@/components/ErrorNotice';
import { MemoryRecordDetail } from './AdminMemoryDetail';
import { RelationshipEvidence } from './AdminRelationshipEvidence';
import { MemoryIndexPanel } from './AdminMemoryIndexPanel';
import { AdminCoreMemoryPanel } from './AdminCoreMemoryPanel';
import { ReflectionRunDetail } from './AdminReflectionDetail';
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
import {
  MEMORY_COLLECTIONS,
  useAdminCharacter,
  useAdminCharacterStates,
  useAdminMemory,
  useAdminReflectionRuns,
  useAdminRelationships,
  useAdminTasks,
  useRefreshRelationshipAttitudes,
  type AdminMemoryItem,
} from '@/api/admin';

/**
 * 角色诊断。
 *
 * 状态、关系、记忆、反思与任务五类事实。记忆按类别切换而不是全部铺开：
 * 四类记忆各自展示覆盖范围或长期事项。
 */
export function AdminCharacterPage() {
  const params = useParams();
  const communityId = params.communityId ?? null;
  const characterId = params.characterId ?? null;

  const character = useAdminCharacter(communityId, characterId);
  const states = useAdminCharacterStates(communityId, characterId);
  const relationships = useAdminRelationships(communityId, characterId, { limit: 30 });
  const [collection, setCollection] = useState<string>(MEMORY_COLLECTIONS[0].value);
  const memory = useAdminMemory(communityId, characterId, collection, { limit: 30 });
  const [runStatus, setRunStatus] = useState('');
  const runs = useAdminReflectionRuns(communityId, characterId, { limit: 20, status: runStatus });
  const tasks = useAdminTasks(communityId, { characterId: characterId ?? '', limit: 20 });
  const relationshipRefresh = useRefreshRelationshipAttitudes(communityId ?? '', characterId ?? '');
  const [relationshipRequestId, setRelationshipRequestId] = useState<string | null>(null);
  async function refreshAllRelationships() {
    const requestId = relationshipRequestId ?? crypto.randomUUID();
    setRelationshipRequestId(requestId);
    try {
      await relationshipRefresh.mutateAsync({ request_id: requestId });
      setRelationshipRequestId(null);
    } catch {
      // 保留请求身份，重试不会创建另一批任务。
    }
  }

  const stateHistory = states.data?.history.items ?? [];
  const relationshipItems = relationships.data?.items ?? [];
  const memoryItems = memory.data?.items ?? [];
  const runItems = runs.data?.items ?? [];
  const taskItems = tasks.data?.items ?? [];

  return (
    <AdminPage
      title={character.data?.display_name ?? characterId ?? '角色'}
      subtitle="状态、关系、记忆、反思与任务。记忆正文与冻结内容属于私有内容。"
    >
      <AdminSection title="实例">
        <AdminListState
          isPending={character.isPending}
          error={character.error}
          isEmpty={false}
          emptyText=""
        >
          <div className="flex flex-col">
            <FieldRow label="标识">{character.data?.character_id}</FieldRow>
            <FieldRow label="模板">
              {character.data?.blueprint_id} v{character.data?.blueprint_version}
            </FieldRow>
            <FieldRow label="可用性">
              {character.data === undefined ? null : (
                <StatusBadge value={character.data.availability_status} />
              )}
            </FieldRow>
            <FieldRow label="不可用原因">{character.data?.availability_reason ?? '—'}</FieldRow>
            <FieldRow label="记忆状态">{character.data?.memory_status ?? '—'}</FieldRow>
            <FieldRow label="准备阶段">{character.data?.memory_phase ?? '—'}</FieldRow>
            <FieldRow label="准备错误">{character.data?.memory_error_code ?? '—'}</FieldRow>
            <FieldRow label="下次检查">
              <TimeCell value={character.data?.next_check_at_utc} />
            </FieldRow>
          </div>
        </AdminListState>
      </AdminSection>

      {communityId && characterId ? <AdminCoreMemoryPanel communityId={communityId} characterId={characterId} fullMode={character.data?.memory_mode === 'full'} /> : null}

      <AdminSection title="状态" count={stateHistory.length}>
        <AdminListState
          isPending={states.isPending}
          error={states.error}
          isEmpty={stateHistory.length === 0}
          emptyText="没有状态记录。"
        >
          <div className="flex flex-col gap-2">
            <FieldRow label="计算时间">
              <TimeCell value={states.data?.effective_at_utc} />
            </FieldRow>
            <AdminTable
              headers={['类型', '数值', '记录时间', '过期时间']}
              rows={stateHistory.map((entry) => ({
                key: entry.entry_id,
                cells: [
                  <MonoCell key="k">{entry.state_kind}</MonoCell>,
                  <MonoCell key="v">{entry.value === '' ? '未记录' : entry.value}</MonoCell>,
                  <TimeCell key="e" value={entry.recorded_at_utc} />,
                  <TimeCell key="x" value={entry.expires_at_utc} />,
                ],
              }))}
            />
          </div>
        </AdminListState>
      </AdminSection>

      <AdminSection title="关系" count={relationshipItems.length} actions={
        <button type="button" onClick={() => void refreshAllRelationships()}
          disabled={character.data?.memory_mode !== 'full' || relationshipRefresh.isPending || relationshipItems.some(
            (item) => ['pending', 'running', 'retry_wait'].includes(item.attitude_refresh?.status ?? ''),
          )}
          className="rounded-lg border border-border-subtle px-3 py-1 text-xs text-accent disabled:opacity-40">
          {relationshipRefresh.isPending ? '安排中…' : relationshipRequestId ? '重试全部整理' : '重新整理全部关系描述'}
        </button>
      }>
        {relationshipRefresh.error ? <ErrorNotice error={relationshipRefresh.error} diagnostic /> : null}
        <AdminListState
          isPending={relationships.isPending}
          error={relationships.error}
          isEmpty={relationshipItems.length === 0}
          emptyText="没有关系记录。"
        >
          {/* 关系逐行可展开：数值在摘要行，证据与态度在展开后。 */}
          <ul className="flex flex-col">
            {relationshipItems.map((relation) => (
              <li
                key={relation.target_kind + relation.target_id}
                className="border-t border-border-subtle/60 py-1"
              >
                <RelationshipEvidence
                  communityId={communityId ?? ''}
                  characterId={characterId ?? ''}
                  relation={relation}
                  fullMode={character.data?.memory_mode === 'full'}
                />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>
      <MemoryIndexPanel communityId={communityId} characterId={characterId} />

      <AdminSection
        title="记忆"
        count={memoryItems.length}
        actions={
          <select
            value={collection}
            onChange={(event) => {
              setCollection(event.target.value);
            }}
            className="rounded-md border border-border-subtle bg-surface-sunken px-2 py-1 text-[11px] outline-none"
          >
            {MEMORY_COLLECTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        }
      >
        <AdminListState
          isPending={memory.isPending}
          error={memory.error}
          isEmpty={memoryItems.length === 0}
          emptyText="这一类没有记录。"
        >
          <ul className="flex flex-col gap-1.5">
            {memoryItems.map((item) => (
              <li key={recordId(item)} className="border-t border-border-subtle/60 pt-1.5">
                <MemoryRow
                  communityId={communityId ?? ''}
                  characterId={characterId ?? ''}
                  collection={collection}
                  item={item}
                />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection
        title="反思"
        count={runItems.length}
        actions={
          <select
            value={runStatus}
            onChange={(event) => {
              setRunStatus(event.target.value);
            }}
            className="rounded-md border border-border-subtle bg-surface-sunken px-2 py-1 text-[11px] outline-none"
          >
            <option value="">全部状态</option>
            {['pending', 'running', 'retry_wait', 'completed', 'partial', 'failed', 'cancelled'].map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        }
      >
        <AdminListState
          isPending={runs.isPending}
          error={runs.error}
          isEmpty={runItems.length === 0}
          emptyText="没有反思运行。"
        >
          <ul className="flex flex-col">
            {runItems.map((run) => (
              <li
                key={run.graph_run_id}
                className="border-t border-border-subtle/60 py-1"
              >
                <AdminDisclosure summary={<>
                    <span className="text-[12px] text-content">{run.graph_kind}</span>
                    <span className="tabular text-[11px] text-content-faint">
                      第 {run.execution_generation} 代
                    </span>
                    <span className="ml-auto flex items-baseline gap-2">
                      <StatusBadge value={run.status} />
                      <TimeCell value={run.created_at_utc} />
                    </span>
                  </>}>
                  <div className="mt-2 pl-2">
                    <ReflectionRunDetail
                      communityId={communityId}
                      characterId={characterId}
                      graphRunId={run.graph_run_id}
                    />
                  </div>
                </AdminDisclosure>
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>

      <AdminSection title="任务" count={taskItems.length}>
        <AdminListState
          isPending={tasks.isPending}
          error={tasks.error}
          isEmpty={taskItems.length === 0}
          emptyText="这个角色没有任务。"
        >
          <AdminTable
            headers={['任务', '会话', '状态', '尝试', '最近失败']}
            rows={taskItems.map((task) => ({
              key: task.task_id,
              cells: [
                <MonoCell key="i">{task.task_id}</MonoCell>,
                <MonoCell key="v">{task.conversation_id}</MonoCell>,
                <StatusBadge key="s" value={task.status} />,
                <MonoCell key="a">{String(task.attempt_count)}</MonoCell>,
                <MonoCell key="f">{task.last_failure?.code ?? '—'}</MonoCell>,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>
    </AdminPage>
  );
}

/**
 * 记忆行。
 *
 * 材料段、连续摘要、事实和认知共用列表，详情展开后分别读取。
 */
function MemoryRow({
  communityId,
  characterId,
  collection,
  item,
}: {
  readonly communityId: string;
  readonly characterId: string;
  readonly collection: string;
  readonly item: AdminMemoryItem;
}) {
  const id = recordId(item);
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-1 py-1.5">
        <span className="min-w-0 flex-1 text-sm text-content-primary">
          {'topic' in item ? item.topic : summarize(item)}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-content-faint">
          {'version' in item ? `${item.status === 'needs_review' ? '需要重新审核' : item.status === 'current' ? '有效' : '历史记录'} · 版本 ${item.version}` : id}
        </span>
      </summary>
      {/* 展开时才读取正文。 */}
      {open ? (
        <div className="mt-2 flex flex-col gap-3">
          <MemoryRecordDetail
            communityId={communityId}
            characterId={characterId}
            collection={collection}
            recordId={id}
          />
        </div>
      ) : null}
    </details>
  );
}

/** 按类别取出正式标识。 */
function recordId(item: AdminMemoryItem): string {
  if ('segment_id' in item) return item.segment_id;
  if ('digest_id' in item) return item.digest_id;
  return item.memory_id;
}

/** 一行摘要，让列表不展开也能看出内容大致是什么。 */
function summarize(item: AdminMemoryItem): string {
  if ('record_kind' in item && item.record_kind === 'segments') {
    return '经历段 ' + item.position + ' · ' + item.scenes.map(scene => scene.boundary.name).join('、');
  }
  if ('record_kind' in item && item.record_kind === 'digests') {
    return '覆盖 ' + item.covered_segments.length + ' 个经历段';
  }
  return item.topic;
}

/** 关系数值可空：没有形成的关系不是零，界面上区分开。 */
function numberOrDash(value: number | null): string {
  return value === null ? '—' : String(value);
}
