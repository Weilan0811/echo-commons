import { useState } from 'react';
import { useAdminCoreMemory, useRefreshCoreMemory } from '@/api/admin';
import { AdminDisclosure, AdminListState, AdminSection, FieldRow, PrivateText, StatusBadge } from '@/components/Admin';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ReflectionRunDetail } from './AdminReflectionDetail';

export function AdminCoreMemoryPanel({ communityId, characterId, fullMode }: {
  readonly communityId: string;
  readonly characterId: string;
  readonly fullMode: boolean;
}) {
  const query = useAdminCoreMemory(communityId, characterId);
  const mutation = useRefreshCoreMemory(communityId, characterId);
  const [requestId, setRequestId] = useState<string | null>(null);
  const current = query.data;
  const progress = current?.refresh;
  const active = ['pending', 'running', 'retry_wait'].includes(progress?.status ?? '');

  async function rebuild() {
    const identity = requestId ?? crypto.randomUUID();
    setRequestId(identity);
    try {
      await mutation.mutateAsync(identity);
      setRequestId(null);
    } catch {
      // 保留请求标识，网络恢复后的重试查询同一次正式任务。
    }
  }

  return <AdminSection title="核心记忆" actions={
    <button type="button" onClick={() => void rebuild()}
      disabled={!fullMode || query.isPending || mutation.isPending || active}
      className="rounded-lg border border-border-subtle px-3 py-1 text-xs text-accent disabled:opacity-40">
      {mutation.isPending ? '安排中…' : active ? '正在重建…' : requestId ? '重试重建' : '重建核心记忆'}
    </button>
  }>
    {mutation.error ? <ErrorNotice error={mutation.error} diagnostic /> : null}
    <AdminListState isPending={query.isPending} error={query.error} isEmpty={false} emptyText="">
      {!fullMode ? <p className="mb-2 text-xs text-content-muted">简单模式使用作者原文与摘要；核心记忆重建用于完整模式。</p> : null}
      <FieldRow label="正文长度">{current?.content.length ?? 0} / {current?.max_chars ?? '—'} 字符</FieldRow>
      <div className="grid gap-3 md:grid-cols-2">
        {progress ? <PrivateText label="重建前的记忆" text={progress.previous_core || '没有核心记忆'} /> : null}
        <PrivateText label="当前生效的记忆" text={current?.content || '没有需要常驻的记忆'} />
      </div>
      <FieldRow label="正文依据">{current?.source_refs.join('、') || '—'}</FieldRow>
      {progress ? <>
        <FieldRow label="重建状态"><StatusBadge value={progress.status ?? 'pending'} /></FieldRow>
        <FieldRow label="记录进度">{progress.processed_count} / {progress.total_count}；未读 {progress.unread_memory_ids.length}</FieldRow>
        <FieldRow label="本轮记录">{progress.selected_memory_ids.join('、') || '没有有效记录'}</FieldRow>
        <FieldRow label="未读记录">{progress.unread_memory_ids.join('、') || '已全部读取'}</FieldRow>
        <FieldRow label="来源读取">{progress.sources_readable ? '完整' : '来源缺失，保留原有记忆'}</FieldRow>
        {progress.error_code ? <FieldRow label="错误类型">{progress.error_code}</FieldRow> : null}
        {progress.graph_run_id ? <AdminDisclosure summary="查看来源、生成结果与实际模型调用">
          <ReflectionRunDetail communityId={communityId} characterId={characterId} graphRunId={progress.graph_run_id} />
        </AdminDisclosure> : null}
      </> : null}
    </AdminListState>
  </AdminSection>;
}
