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
 * 五类记录的字段差别很大：材料段讲覆盖范围与消费情况，长期页讲置信度与
 * 可见性，实体讲别名与关联。按 record_kind 分别渲染，而不是把所有字段平铺
 * 成一张表——平铺后每类都有大片不适用字段，读者无法判断该看哪几行。
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
  if (record.record_kind === 'entries') return <EntryDetailView record={record} />;
  if (record.record_kind === 'entities') return <EntityDetailView record={record} />;
  return <EdgeDetailView record={record} />;
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

/** 长期页详情。置信度与显著性是反思给出的判断，来源与失效时间决定可用性。 */
function EntryDetailView({ record }: { readonly record: Extract<Record_, { record_kind: 'entries' }> }) {
  return (
    <>
      <div className="flex flex-col">
        <FieldRow label="标识">{record.memory_id}</FieldRow>
        <FieldRow label="类别">{record.memory_kind}</FieldRow>
        <FieldRow label="主体">
          {record.subject_kind}:{record.subject_id}
        </FieldRow>
        <FieldRow label="可见性">{record.visibility}</FieldRow>
        <FieldRow label="置信度">{record.confidence}</FieldRow>
        <FieldRow label="显著性">{record.salience}</FieldRow>
        <FieldRow label="来源">
          {record.source_kind}:{record.source_ref}
        </FieldRow>
        <FieldRow label="内容版本">{record.content_version}</FieldRow>
        <FieldRow label="发生时间">
          <TimeCell value={record.occurred_at_utc} />
        </FieldRow>
        <FieldRow label="失效时间">
          <TimeCell value={record.invalidated_at_utc} />
        </FieldRow>
        <FieldRow label="到期时间">
          <TimeCell value={record.expires_at_utc} />
        </FieldRow>
      </div>

      <PrivateText label="正文" text={record.content} />

      {record.batch === null ? null : (
        <div className="flex flex-col">
          <FieldRow label="来源批次">{record.batch.batch_id}</FieldRow>
          <FieldRow label="批次前驱">{record.batch.previous_digest_id ?? '—'}</FieldRow>
        </div>
      )}

      <AdminTable
        headers={['关联实体', '关系']}
        rows={record.entities.map((entity) => ({
          key: entity.entity_id,
          cells: [
            <MonoCell key="i">{entity.entity_id}</MonoCell>,
            <MonoCell key="r">{entity.role}</MonoCell>,
          ],
        }))}
        emptyText="没有关联实体."
      />
    </>
  );
}

/** 实体详情。实体自身没有正文，可读内容是别名与指向它的长期页。 */
function EntityDetailView({
  record,
}: {
  readonly record: Extract<Record_, { record_kind: 'entities' }>;
}) {
  return (
    <>
      <div className="flex flex-col">
        <FieldRow label="标识">{record.entity_id}</FieldRow>
        <FieldRow label="类别">{record.entity_kind}</FieldRow>
        <FieldRow label="规范名">{record.canonical_name}</FieldRow>
        <FieldRow label="失效时间">
          <TimeCell value={record.invalidated_at_utc} />
        </FieldRow>
      </div>

      <AdminTable
        headers={['别名', '归一化', '失效时间']}
        rows={record.aliases.map((alias) => ({
          key: alias.alias_id,
          cells: [
            <MonoCell key="a">{alias.alias_text}</MonoCell>,
            <MonoCell key="n">{alias.normalized_alias}</MonoCell>,
            <TimeCell key="i" value={alias.invalidated_at_utc} />,
          ],
        }))}
        emptyText="没有别名。"
      />

      <AdminTable
        headers={['长期页', '关系']}
        rows={record.memories.map((memory) => ({
          key: memory.memory_id,
          cells: [
            <MonoCell key="m">{memory.memory_id}</MonoCell>,
            <MonoCell key="r">{memory.role}</MonoCell>,
          ],
        }))}
        emptyText="没有指向该实体的长期页。"
      />
    </>
  );
}

/**
 * 实体关系详情。
 *
 * source_memory_id 为空表示这条关系没有来源长期页，可能是本次反思直接
 * 提出的推断。排障时要区分「有依据」与「模型推断」，因此单独标注。
 */
function EdgeDetailView({ record }: { readonly record: Extract<Record_, { record_kind: 'edges' }> }) {
  return (
    <div className="flex flex-col">
      <FieldRow label="标识">{record.edge_id}</FieldRow>
      <FieldRow label="方向">
        {record.from_entity_id} — {record.edge_kind} → {record.to_entity_id}
      </FieldRow>
      <FieldRow label="置信度">{record.confidence}</FieldRow>
      <FieldRow label="来源长期页">{record.source_memory_id ?? '无，属于模型推断'}</FieldRow>
      <FieldRow label="失效时间">
        <TimeCell value={record.invalidated_at_utc} />
      </FieldRow>
    </div>
  );
}
