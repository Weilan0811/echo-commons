import { useState } from 'react';
import { AdminListState, AdminTable, MonoCell, TimeCell } from '@/components/Admin';
import { useAdminEvidence, type AdminRelationship } from '@/api/admin';

const SUMMARY = 'flex cursor-pointer items-baseline gap-3';
const LABEL = 'min-w-0 flex-1 truncate text-[12px]';
const DIM = 'shrink-0 text-[12px] text-content-faint';
const NUM = 'tabular shrink-0 text-[12px] text-content-muted';
const CELL = 'text-[12px] text-content-muted';
const TAG = 'text-[11px] text-content-faint';

/**
 * 关系证据。
 *
 * 关系数值是结论，证据是得出结论的依据。关系良好但没有任何证据，说明数值
 * 来自模型推断而不是观察，这类情况在排障时必须能一眼看出，因此证据按行展开
 * 读取，而不是在关系表里统一列出。
 */
export function RelationshipEvidence({ communityId, characterId, relation }: Props) {
  const [open, setOpen] = useState(false);
  const target = open ? { kind: relation.target_kind, id: relation.target_id } : null;
  const evidence = useAdminEvidence(open ? communityId : null, open ? characterId : null, target, {
    limit: 30,
  });
  const items = evidence.data?.items ?? [];

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={SUMMARY}>
        <span className={LABEL}>
          {relation.target_kind}:{relation.target_id}
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
            emptyText="没有证据。这条关系可能来自模型推断而不是实际观察。"
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