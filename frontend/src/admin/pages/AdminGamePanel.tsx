import { useState } from 'react';
import { useAdminGameInspection, useAdminGameRecords, type AdminGameRecordKind } from '@/api/admin';
import {
  AdminDisclosure,
  AdminListState,
  AdminSection,
  FieldRow,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import { ErrorNotice } from '@/components/ErrorNotice';

const recordLabels: Record<AdminGameRecordKind, string> = {
  events: '事件时间线',
  actions: '落子回执',
  operations: '生命周期回执',
};

export function AdminGamePanel({
  communityId,
  conversationId,
}: {
  communityId: string;
  conversationId: string;
}) {
  const inspection = useAdminGameInspection(communityId, conversationId);
  const [kind, setKind] = useState<AdminGameRecordKind>('events');
  const records = useAdminGameRecords(communityId, conversationId, kind);
  const game = inspection.data?.game;
  const items = records.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <AdminSection
      title="游戏对局"
      actions={
        <button
          className="rounded border border-border-subtle px-3 py-1 text-xs"
          onClick={() => {
            void inspection.refetch();
            void records.refetch();
          }}
        >
          刷新对局记录
        </button>
      }
    >
      <AdminListState
        isPending={inspection.isPending}
        error={inspection.error}
        isEmpty={false}
        emptyText=""
      >
        {game ? (
          <>
            <FieldRow label="对局标识">{game.game_id}</FieldRow>
            <FieldRow label="游戏规则">
              {game.game_type} · {game.ruleset_id} v{game.ruleset_version}
            </FieldRow>
            <FieldRow label="状态">
              <StatusBadge value={game.status} />
            </FieldRow>
            <FieldRow label="状态版本">{game.state_version}</FieldRow>
            <FieldRow label="最后变化">
              <TimeCell value={game.updated_at_utc} />
            </FieldRow>
            <AdminDisclosure summary="完整状态与参与区间">
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all p-3 text-xs">
                {JSON.stringify(inspection.data, null, 2)}
              </pre>
            </AdminDisclosure>
          </>
        ) : null}
      </AdminListState>
      <div className="my-4 flex flex-wrap gap-2" aria-label="对局记录类型">
        {Object.entries(recordLabels).map(([value, label]) => (
          <button
            key={value}
            aria-pressed={kind === value}
            className={`rounded border px-3 py-2 text-xs ${kind === value ? 'border-accent text-accent' : 'border-border-subtle text-content-muted'}`}
            onClick={() => setKind(value as AdminGameRecordKind)}
          >
            {label}
          </button>
        ))}
      </div>
      {records.error ? (
        <ErrorNotice error={records.error} onRetry={() => void records.refetch()} />
      ) : null}
      {records.isPending ? (
        <p role="status" className="text-xs text-content-muted">
          正在读取对局记录…
        </p>
      ) : (
        <>
          {items.length === 0 ? (
            <p className="text-xs text-content-faint">暂无{recordLabels[kind]}。</p>
          ) : (
            <ol className="space-y-3">
              {items.map((record) => (
                <li key={record.record_id} className="border-t border-border-subtle pt-3">
                  <AdminDisclosure
                    summary={
                      <>
                        <span className="text-xs">
                          {kind === 'events' ? '事件序号' : '状态版本'} {record.position}
                        </span>
                        <code className="min-w-0 break-all text-xs text-content-muted">
                          {String(
                            record.document.type ??
                              record.document.operation ??
                              record.document.request_id ??
                              record.record_id,
                          )}
                        </code>
                      </>
                    }
                  >
                    {record.command ? (
                      <>
                        <p className="mt-3 text-xs text-content-faint">原请求</p>
                        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all py-2 text-xs">
                          {JSON.stringify(record.command, null, 2)}
                        </pre>
                      </>
                    ) : null}
                    <p className="mt-3 text-xs text-content-faint">
                      {kind === 'events' ? '正式事件' : '执行回执'}
                    </p>
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all py-2 text-xs">
                      {JSON.stringify(record.document, null, 2)}
                    </pre>
                  </AdminDisclosure>
                </li>
              ))}
            </ol>
          )}
          {records.hasNextPage ? (
            <button
              className="mt-4 rounded border border-border-subtle px-3 py-2 text-xs"
              disabled={records.isFetching}
              onClick={() => void records.fetchNextPage()}
            >
              读取更多对局记录
            </button>
          ) : null}
        </>
      )}
    </AdminSection>
  );
}
