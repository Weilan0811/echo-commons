import {
  AdminListState,
  AdminTable,
  FieldRow,
  MonoCell,
  PrivateText,
  TimeCell,
} from '@/components/Admin';
import { useAdminMemoryRecord, type AdminMemoryDetail } from '@/api/admin';

type Record_ = AdminMemoryDetail;

/**
 * 记忆详情。
 *
 * 材料段展示覆盖范围和消费情况，连续摘要展示压缩范围，事实和认知展示正文、逐项依据与版本。
 */
export function MemoryRecordDetail({
  communityId,
  characterId,
  collection,
  recordId,
}: {
  readonly communityId: string | null;
  readonly characterId: string | null;
  readonly collection: string;
  readonly recordId: string;
}) {
  const detail = useAdminMemoryRecord(communityId, characterId, collection, recordId);
  const record = detail.data;

  return (
    <AdminListState
      isPending={detail.isPending}
      error={detail.error}
      isEmpty={record === undefined}
      emptyText=""
    >
      {record === undefined ? null : <MemoryDetailBody record={record} />}
    </AdminListState>
  );
}

/** 按 record_kind 分派到各类视图。不做整体断言，断言会掩盖类型不匹配。 */
function MemoryDetailBody({ record }: { readonly record: Record_ }) {
  if (record.record_kind === 'segments') return <SegmentDetailView record={record} />;
  if (record.record_kind === 'digests') return <DigestDetailView record={record} />;
  return <LongTermDetailView record={record} />;
}

/**
 * 材料段详情。
 *
 * 消费情况决定这段材料是否已被长期整理消费。未消费、已消费和重复消费在
 * 排障时含义完全不同，因此单独列表呈现，不折叠成一句计数。
 */
function SegmentDetailView({
  record,
}: {
  readonly record: Extract<Record_, { record_kind: 'segments' }>;
}) {
  return (
    <>
      <div className="flex flex-col">
        <FieldRow label="标识">{record.segment_id}</FieldRow>
        <FieldRow label="会话">{record.conversation_id}</FieldRow>
        <FieldRow label="序号范围">
          {record.first_message_sequence} – {record.last_message_sequence}
        </FieldRow>
        <FieldRow label="状态">{record.status}</FieldRow>
        <FieldRow label="封段时间">
          <TimeCell value={record.sealed_at_utc} />
        </FieldRow>
        <FieldRow label="消化时间">
          <TimeCell value={record.ingested_at_utc} />
        </FieldRow>
        <FieldRow label="摘要版本">{record.summary_version}</FieldRow>
      </div>

      <PrivateText label="段摘要" text={record.summary_text} />

      {/* 来源快照是 sources 的整体序列化，直接展示会是一长串 JSON，因此折叠。 */}
      <PrivateText label="来源快照" text={record.source_version} />

      <AdminTable
        headers={['来源', '标识', '版本']}
        rows={record.sources.map((source) => ({
          key: source.ordinal.toString(),
          cells: [
            <MonoCell key="k">{source.source_kind}</MonoCell>,
            <MonoCell key="s">{source.source_id}</MonoCell>,
            <MonoCell key="v">{source.source_version}</MonoCell>,
          ],
        }))}
        emptyText="没有来源段。"
      />

      <AdminTable
        headers={['摘要批次', '结果', '消费时间']}
        rows={record.consumption.map((item) => ({
          key: item.batch_id,
          cells: [
            <MonoCell key="b">{item.batch_id}</MonoCell>,
            <MonoCell key="o">{item.outcome}</MonoCell>,
            <TimeCell key="t" value={item.consumed_at_utc} />,
          ],
        }))}
        emptyText="尚未被任何摘要批次消费。"
      />

      <AdminTable
        headers={['归属', '来源', '版本']}
        rows={record.coverage.map((item) => ({
          key: item.owner_kind + item.owner_id + item.source_id,
          cells: [
            <MonoCell key="o">
              {item.owner_kind}:{item.owner_id}
            </MonoCell>,
            <MonoCell key="s">
              {item.source_kind}:{item.source_id}
            </MonoCell>,
            <MonoCell key="v">{item.source_version}</MonoCell>,
          ],
        }))}
        emptyText="没有覆盖记录。"
      />
    </>
  );
}

/** 连续摘要详情。前驱摘要决定覆盖连续性，缺失时说明来源。 */
function DigestDetailView({
  record,
}: {
  readonly record: Extract<Record_, { record_kind: 'digests' }>;
}) {
  return (
    <>
      <div className="flex flex-col">
        <FieldRow label="标识">{record.digest_id}</FieldRow>
        <FieldRow label="批次">{record.batch_id}</FieldRow>
        <FieldRow label="会话">{record.conversation_id}</FieldRow>
        <FieldRow label="覆盖至序号">{record.covers_through_sequence}</FieldRow>
        <FieldRow label="内容版本">{record.content_version}</FieldRow>
        <FieldRow label="创建时间">
          <TimeCell value={record.created_at_utc} />
        </FieldRow>
      </div>

      <PrivateText label="摘要正文" text={record.content} />

      <div className="flex flex-col">
        <FieldRow label="前驱摘要">{record.batch.previous_digest_id ?? '—'}</FieldRow>
        <FieldRow label="来源版本">{record.batch.source_version}</FieldRow>
        <FieldRow label="批次会话">{record.batch.conversation_id}</FieldRow>
      </div>

      <AdminTable
        headers={['来源段', '摘要版本']}
        rows={record.batch.sources.map((source) => ({
          key: source.segment_id,
          cells: [
            <MonoCell key="s">{source.segment_id}</MonoCell>,
            <MonoCell key="v">{source.summary_version}</MonoCell>,
          ],
        }))}
        emptyText="批次没有记录来源段。"
      />
    </>
  );
}

type LongTermDetail = Extract<Record_, { record_kind: 'facts' | 'cognitions' }>;

function LongTermDetailView({ record }: { readonly record: LongTermDetail }) {
  return (
    <>
      <div className="flex flex-col">
        <FieldRow label="事项">{record.topic}</FieldRow>
        <FieldRow label="状态">
          {record.status === 'current' ? '有效' : record.status === 'needs_review' ? '需要重新审核' : '历史记录'}
        </FieldRow>
        <FieldRow label="版本">{record.version}</FieldRow>
        {record.record_kind === 'facts' ? (
          <>
            <FieldRow label="发生或表达时间"><TimeCell value={record.occurred_at_utc} /></FieldRow>
            <FieldRow label="获知时间"><TimeCell value={record.learned_at_utc} /></FieldRow>
            <FieldRow label="适用条件">{record.conditions || '未限定'}</FieldRow>
          </>
        ) : (
          <>
            <FieldRow label="整理形成时间"><TimeCell value={record.formed_at_utc} /></FieldRow>
            <FieldRow label="适用范围">{record.applies_to}</FieldRow>
          </>
        )}
        <FieldRow label="保存时间"><TimeCell value={record.recorded_at_utc} /></FieldRow>
      </div>
      <PrivateText label={record.record_kind === 'facts' ? '事实正文' : '角色认识'} text={record.content} />
      <SourceDetails sources={record.sources} />
      {record.stages.length > 0 ? (
        <AdminTable headers={['整理阶段', '结果', '完成时间']}
          rows={record.stages.map(stage => ({ key: stage.stage, cells: [
            <span key="s">{stage.stage === 'facts' ? '事实审核与保存' : '认知整理与保存'}</span>,
            <span key="o">{stage.outcome === 'no_op' ? '已处理，无新增内容' : '已保存'}</span>,
            <TimeCell key="t" value={stage.completed_at_utc} />,
          ] }))} />
      ) : null}
      <details className="rounded-lg border border-border-subtle p-3">
        <summary className="cursor-pointer text-sm text-content-muted">记录信息与历史版本</summary>
        <FieldRow label="标识">{record.memory_id}</FieldRow>
        <FieldRow label="来源批次">{record.source_ref}</FieldRow>
        {record.versions.filter(version => version.version !== record.version).map(version => (
          <details key={version.version} className="mt-3 border-t border-border-subtle pt-3">
            <summary className="cursor-pointer text-sm text-content-muted">版本 {version.version} · <TimeCell value={version.recorded_at_utc} /></summary>
            <PrivateText label="当时内容" text={version.content} />
            <SourceDetails sources={version.sources} />
          </details>
        ))}
      </details>
    </>
  );
}

function SourceDetails({ sources }: { readonly sources: LongTermDetail['sources'] }) {
  const labels: Readonly<Record<string, string>> = {
    message: '原始消息', thought: '自身内心记录', author_chunk: '作者原文', memory_fact: '支持事实',
  };
  return <div className="flex flex-col gap-2">{sources.map(source => (
    <details key={`${source.source_kind}:${source.source_id}:${source.source_version}`}
      className="rounded-lg border border-border-subtle p-3">
      <summary className="cursor-pointer text-sm text-content-muted">
        {labels[source.source_kind] ?? source.source_kind} · 版本 {source.source_version}
        {source.readable ? '' : ' · 原文不可读取'}
      </summary>
      <FieldRow label="来源标识">{source.source_id}</FieldRow>
      <PrivateText label="依据正文" text={source.content ?? '来源正文不可读取。'} />
    </details>
  ))}</div>;
}
