import { AdminListState, AdminSection, FieldRow, MonoCell, PrivateText } from '@/components/Admin';
import { useAdminMemoryIndex } from '@/api/admin';

/**
 * 记忆索引状态。
 *
 * 检索结果不完整时先看这里：文档数说明有多少材料应该可查，向量数与是否启用
 * 说明用的是全文投影还是向量检索，失败列表说明有没有材料根本没进去。
 *
 * 界面不提供重建入口。重建会触发后台任务并可能消耗模型额度，属于写操作，
 * 与管理端不做写操作入口的决定一致；需要时用命令行执行。
 */
export function MemoryIndexPanel({
  communityId,
  characterId,
}: {
  readonly communityId: string | null;
  readonly characterId: string | null;
}) {
  const index = useAdminMemoryIndex(communityId, characterId);
  const data = index.data;
  const failureCount = data?.failures.length ?? 0;

  return (
    <AdminSection title="记忆索引">
      <AdminListState
        isPending={index.isPending}
        error={index.error}
        isEmpty={false}
        emptyText=""
      >
        <div className="flex flex-col">
          <FieldRow label="可检索文档">{data?.documents}</FieldRow>
          <FieldRow label="向量数">{vectorText(data?.vectors, data?.vector_enabled)}</FieldRow>
          <FieldRow label="向量模型">{data?.model_identity ?? '未启用'}</FieldRow>
        </div>

        {failureCount > 0 ? (
          <div className="mt-2 flex flex-col gap-1.5">
            <p className="text-[12px] text-danger">
              有 {failureCount} 条索引失败记录，检索结果可能不完整。
            </p>
            {data?.failures.map((failure) => (
              <PrivateText key={`${failure.source_kind}:${failure.source_id}`}
                label={`${failure.source_kind} · ${failure.source_id}`}
                text={`${failure.error_code} · 供应商尝试 ${failure.provider_attempts} 次 · ${failure.recorded_at_utc}`} />
            ))}
          </div>
        ) : null}
      </AdminListState>
    </AdminSection>
  );
}

/** 向量数为零时说明原因：未启用与已启用但没建成是两回事。 */
function vectorText(vectors: number | undefined, enabled: boolean | undefined): string {
  if (vectors === undefined) return '';
  if (vectors > 0) return String(vectors);
  return enabled ? '0（已启用但尚未建成）' : '0（未启用向量，使用全文投影）';
}
