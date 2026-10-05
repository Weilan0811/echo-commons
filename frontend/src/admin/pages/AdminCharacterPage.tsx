import { useState } from 'react';
import { useParams } from 'react-router';
import {
  AdminPage,
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
  type AdminMemoryItem,
} from '@/api/admin';

/**
 * 角色诊断。
 *
 * 状态、关系、记忆、反思与任务五类事实。记忆按类别切换而不是全部铺开：
 * 五类记录的字段完全不同，混在一屏里没有可读性。
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
            <FieldRow label="下次检查">
              <TimeCell value={character.data?.next_check_at_utc} />
            </FieldRow>
          </div>
        </AdminListState>
      </AdminSection>

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
                  <MonoCell key="v">{entry.value}</MonoCell>,
                  <TimeCell key="e" value={entry.recorded_at_utc} />,
                  <TimeCell key="x" value={entry.expires_at_utc} />,
                ],
              }))}
            />
          </div>
        </AdminListState>
      </AdminSection>

      <AdminSection title="关系" count={relationshipItems.length}>
        <AdminListState
          isPending={relationships.isPending}
          error={relationships.error}
          isEmpty={relationshipItems.length === 0}
          emptyText="没有关系记录。"
        >
          <AdminTable
            headers={['对象', '关系', '好感', '信任', '依附', '版本']}
            rows={relationshipItems.map((relation) => ({
              key: relation.target_kind + relation.target_id,
              cells: [
                <MonoCell key="t">
                  {relation.target_kind}:{relation.target_id}
                </MonoCell>,
                <MonoCell key="y">{relation.relationship_type}</MonoCell>,
                <MonoCell key="a">{numberOrDash(relation.affection)}</MonoCell>,
                <MonoCell key="r">{numberOrDash(relation.trust)}</MonoCell>,
                <MonoCell key="d">{numberOrDash(relation.attachment)}</MonoCell>,
                <MonoCell key="n">{String(relation.state_version)}</MonoCell>,
              ],
            }))}
          />
        </AdminListState>
      </AdminSection>
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
                <MemoryRow collection={collection} item={item} />
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
            {['pending', 'processing', 'completed', 'failed', 'rejected'].map((status) => (
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
          <AdminTable
            headers={['图运行', '图类型', '状态', '代次', '创建时间']}
            rows={runItems.map((run) => ({
              key: run.graph_run_id,
              cells: [
                <MonoCell key="i">{run.graph_run_id}</MonoCell>,
                <MonoCell key="k">{run.graph_kind}</MonoCell>,
                <StatusBadge key="s" value={run.status} />,
                <MonoCell key="r">{String(run.execution_generation)}</MonoCell>,
                <TimeCell key="c" value={run.created_at_utc} />,
              ],
            }))}
          />
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
 * 五类记录的字段差别很大，界面只展示各类共有的标识与时间，正文折叠。
 * 不把某一类的字段当成通用字段渲染，那会让切类别时读起来像坏了。
 */
function MemoryRow({ collection, item }: { readonly collection: string; readonly item: AdminMemoryItem }) {
  return (
    <details>
      <summary className="flex cursor-pointer items-baseline gap-3">
        <span className="tabular w-40 shrink-0 truncate text-[12px] text-content-muted">
          {recordId(item)}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-content-faint">
          {summarize(item)}
        </span>
      </summary>
      <div className="mt-1.5 flex flex-col gap-1.5">
        <PrivateText label={collection + ' 概要'} text={JSON.stringify(item, null, 2)} />
      </div>
    </details>
  );
}

/** 五类记录的主键字段名不同，按类别取出标识。 */
function recordId(item: AdminMemoryItem): string {
  if ('segment_id' in item) return item.segment_id;
  if ('digest_id' in item) return item.digest_id;
  if ('memory_id' in item) return item.memory_id;
  if ('entity_id' in item) return item.entity_id;
  return item.edge_id;
}

/** 一行摘要，让列表不展开也能看出内容大致是什么。 */
function summarize(item: AdminMemoryItem): string {
  if ('record_kind' in item && item.record_kind === 'entities') return item.canonical_name;
  if ('record_kind' in item && item.record_kind === 'edges') {
    return item.from_entity_id + ' -' + item.edge_kind + '-> ' + item.to_entity_id;
  }
  if ('record_kind' in item && item.record_kind === 'segments') {
    return '序号 ' + item.first_message_sequence + '–' + item.last_message_sequence;
  }
  if ('record_kind' in item && item.record_kind === 'digests') {
    return '覆盖至序号 ' + item.covers_through_sequence;
  }
  return item.memory_kind;
}

/** 关系数值可空：没有形成的关系不是零，界面上区分开。 */
function numberOrDash(value: number | null): string {
  return value === null ? '—' : String(value);
}