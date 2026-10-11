import { useState } from 'react';
import { AdminDisclosure, AdminListState, AdminTable, MonoCell, StatusBadge, TimeCell } from '@/components/Admin';
import { useAdminEvidence, useRefreshRelationshipAttitudes, type AdminRelationship } from '@/api/admin';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ReflectionRunDetail } from './AdminReflectionDetail';

const SUMMARY = 'flex cursor-pointer items-baseline gap-3';
const LABEL = 'min-w-0 flex-1 truncate text-[12px]';
const DIM = 'shrink-0 text-[12px] text-content-faint';
const NUM = 'tabular shrink-0 text-[12px] text-content-muted';
const CELL = 'text-[12px] text-content-muted';
const TAG = 'text-[11px] text-content-faint';

/** 逐个目标查看正式关系、描述刷新进度与真实证据。 */
export function RelationshipEvidence({ communityId, characterId, relation, fullMode }: Props) {
  const [open, setOpen] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const refresh = useRefreshRelationshipAttitudes(communityId, characterId);
  const progress = relation.attitude_refresh;
  const active = ['pending', 'running', 'retry_wait'].includes(progress?.status ?? '');
  async function rebuild() {
    const identity = requestId ?? crypto.randomUUID();
    setRequestId(identity);
    try {
      await refresh.mutateAsync({ request_id: identity,
        target: { kind: relation.target_kind, actor_id: relation.target_id } });
      setRequestId(null);
    } catch {
      // 网络失败后沿用同一请求，避免重新创建刷新任务。
    }
  }
  const target = open ? { kind: relation.target_kind, id: relation.target_id } : null;
  const evidence = useAdminEvidence(open ? communityId : null, open ? characterId : null, target, {
    limit: 30,
  });
  const items = evidence.data?.items ?? [];

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={SUMMARY}>
        <span className={LABEL}>
          {relation.target_name}
        </span>
        <span className={DIM}>{relation.relationship_type}</span>
        <span className={NUM}>
          {numberOrDash(relation.affection)} / {numberOrDash(relation.trust)} /{' '}
          {numberOrDash(relation.attachment)}
        </span>
      </summary>

      {open ? (
        <div className="mt-2 flex flex-col gap-2 pl-2">
          <div className="flex flex-col">
            <RelationField label="态度概述">{relation.attitude_summary}</RelationField>
            <RelationField label="目标身份">{`${relation.target_kind}:${relation.target_id}`}</RelationField>
            <div className="my-2 flex items-center gap-3">
              <button type="button" onClick={() => void rebuild()}
                disabled={!fullMode || relation.relationship_type === 'stranger' || refresh.isPending || active}
                className="rounded-lg border border-border-subtle px-3 py-1 text-xs text-accent disabled:opacity-40">
                {refresh.isPending ? '安排中…' : active ? '正在整理…' : requestId ? '重试整理' : '重新整理关系描述'}
              </button>
              {progress?.status ? <StatusBadge value={progress.status} /> : null}
            </div>
            {refresh.error ? <ErrorNotice error={refresh.error} diagnostic /> : null}
            {progress?.error_code ? <RelationField label="刷新诊断">{progress.error_code}</RelationField> : null}
            {progress ? <RelationField label="来源版本">{progress.source_version}</RelationField> : null}
            {progress?.graph_run_id ? <AdminDisclosure summary="查看关系描述生成与恢复">
              <ReflectionRunDetail communityId={communityId} characterId={characterId} graphRunId={progress.graph_run_id} />
            </AdminDisclosure> : null}
            {relation.friend_qualifying_evidence_id === null ? null : (
              <RelationField label="友谊依据">
                {relation.friend_qualifying_evidence_id}
              </RelationField>
            )}
          </div>

          <AdminListState
            isPending={evidence.isPending}
            error={evidence.error}
            isEmpty={items.length === 0}
            emptyText="没有正式关系证据，需要检查初始化来源。"
          >
            <AdminTable
              headers={['证据种类', '来源', '发生时间', '记录时间']}
              rows={items.map((item) => ({
                key: item.evidence_id,
                cells: [
                  <MonoCell key="k">{item.evidence_kind}</MonoCell>,
                  <MonoCell key="s">
                    {item.source_kind}:{item.source_ref}
                  </MonoCell>,
                  <TimeCell key="o" value={item.occurred_at_utc} />,
                  <TimeCell key="r" value={item.recorded_at_utc} />,
                ],
              }))}
            />
          </AdminListState>
        </div>
      ) : null}
    </details>
  );
}

interface Props {
  readonly communityId: string;
  readonly characterId: string;
  readonly relation: AdminRelationship;
  readonly fullMode: boolean;
}

/** 关系里的长文本标签，例如态度概述。 */
function RelationField({ label, children }: { readonly label: string; readonly children: string }) {
  return (
    <div className="flex flex-col py-0.5">
      <span className={TAG}>{label}</span>
      <span className={CELL}>{children === '' ? '未记录。' : children}</span>
    </div>
  );
}

/** 关系数值可空：没有形成的关系不是零，界面上区分开。 */
function numberOrDash(value: number | null): string {
  return value === null ? '—' : String(value);
}
