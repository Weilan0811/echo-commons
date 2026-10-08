import { useState } from 'react';
import {
  AdminListState,
  FieldRow,
  PrivateText,
  StatusBadge,
  TimeCell,
} from '@/components/Admin';
import { useAdminNodeInput, useAdminReflectionRun, type AdminReflectionDetail } from '@/api/admin';

type Node = AdminReflectionDetail['node_tasks'][number];
type Graph = AdminReflectionDetail['graph_run'];

/**
 * 反思图详情。
 *
 * 一次执行是一个图，图由节点组成，节点产出产物，产物汇总成审核结果，最后写入
 * 事实。排障要回答的是「这个节点为什么没跑」和「这个结论凭什么」，所以节点表
 * 与产物表都要能逐项展开，只给一个图状态不够。
 */
export function ReflectionRunDetail({ communityId, characterId, graphRunId }: Props) {
  const run = useAdminReflectionRun(communityId, characterId, graphRunId);
  const detail = run.data;

  return (
    <AdminListState isPending={run.isPending} error={run.error} isEmpty={false} emptyText="">
      {detail === undefined ? null : (
        <div className="flex flex-col gap-4">
          <GraphFacts graph={detail.graph_run} />
          <NodeTable
            communityId={communityId}
            characterId={characterId}
            graphRunId={graphRunId}
            topology={detail.graph_run.topology_node_keys}
            nodes={detail.node_tasks}
            artifacts={detail.artifacts}
          />
          <ResultView detail={detail} />
        </div>
      )}
    </AdminListState>
  );
}

interface Props {
  readonly communityId: string | null;
  readonly characterId: string | null;
  readonly graphRunId: string;
}
function GraphFacts({ graph }: { readonly graph: Graph }) {
  return (
    <div className="flex flex-col">
      <FieldRow label="图类型">{graph.graph_kind}</FieldRow>
      <FieldRow label="状态">
        <StatusBadge value={graph.status} />
      </FieldRow>
      <FieldRow label="执行代次">{graph.execution_generation}</FieldRow>
      <FieldRow label="来源范围">{sourceText(graph)}</FieldRow>
      <FieldRow label="上下文快照">{graph.context_snapshot_id}</FieldRow>
      <FieldRow label="拓扑节点">{graph.topology_node_keys.join('、')}</FieldRow>
      <FieldRow label="必需节点">{graph.required_node_keys.join('、')}</FieldRow>
      <FieldRow label="最近错误">{graph.last_error_code ?? '—'}</FieldRow>
      <FieldRow label="完成时间">
        <TimeCell value={graph.completed_at_utc} />
      </FieldRow>
    </div>
  );
}

/**
 * 节点表。
 *
 * 节点按拓扑顺序排列而不是接口返回顺序：依赖关系决定执行顺序，按返回顺序看会
 * 出现「依赖还没跑就已经完成」的错觉。
 */
function NodeTable({ communityId, characterId, graphRunId, topology, nodes, artifacts }: NodeTableProps) {
  const ordered = [...nodes].sort(
    (left, right) => topology.indexOf(left.node_key) - topology.indexOf(right.node_key),
  );
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-content-faint">节点</span>
      {ordered.map((node) => (
        <NodeRow
          key={node.task_id}
          communityId={communityId}
          characterId={characterId}
          graphRunId={graphRunId}
          node={node}
          artifacts={artifacts.filter((item) => item.node_task_id === node.task_id)}
        />
      ))}
    </div>
  );
}

interface NodeTableProps {
  readonly topology: readonly string[];
  readonly communityId: string | null;
  readonly characterId: string | null;
  readonly graphRunId: string;
  readonly nodes: readonly Node[];
  readonly artifacts: AdminReflectionDetail['artifacts'];
}
/**
 * 节点行。
 *
 * 「已激活」与「状态」分开显示：未激活的节点状态是 skipped，那是拓扑决定的正常
 * 结果而不是失败。节点输入按需读取，未具备时明确说明而不是显示空内容。
 */
function NodeRow({ communityId, characterId, graphRunId, node, artifacts }: NodeRowProps) {
  const [open, setOpen] = useState(false);
  const input = useAdminNodeInput(
    open ? communityId : null,
    open ? characterId : null,
    open ? graphRunId : null,
    open ? node.task_id : null,
  );

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-2">
        <span className="text-[12px] text-content">{node.node_key}</span>
        <span className="text-[11px] text-content-faint">{node.node_kind}</span>
        <span className="ml-auto flex items-baseline gap-2">
          {node.activated === true ? null : (
            <span className="text-[11px] text-content-faint">未激活</span>
          )}
          <StatusBadge value={node.status} />
        </span>
      </summary>

      {open ? (
        <div className="mt-2 flex flex-col gap-2 pl-2">
          <div className="flex flex-col">
            <FieldRow label="任务">{node.task_id}</FieldRow>
            <FieldRow label="依赖节点">{node.dependency_keys.join('、') || '无'}</FieldRow>
            <FieldRow label="输出契约">{node.output_contract?.kind ?? '—'}</FieldRow>
            <FieldRow label="尝试次数">{node.attempt_count}</FieldRow>
            <FieldRow label="租约代次">{node.lease_generation}</FieldRow>
            <FieldRow label="最近错误">{node.last_error_code ?? '—'}</FieldRow>
            <FieldRow label="可用时间">
              <TimeCell value={node.available_at_utc} />
            </FieldRow>
          </div>

          <NodeInputView state={input} />

          {artifacts.length === 0 ? (
            <p className="text-[12px] text-content-faint">这个节点没有产物。</p>
          ) : (
            artifacts.map((artifact) => (
              <ArtifactView key={artifact.artifact_id} artifact={artifact} />
            ))
          )}
        </div>
      ) : null}
    </details>
  );
}
interface NodeRowProps {
  readonly communityId: string | null;
  readonly characterId: string | null;
  readonly graphRunId: string;
  readonly node: Node;
  readonly artifacts: AdminReflectionDetail['artifacts'];
}

/** 节点产物：内容、审核与证据分开，证据决定结论能追溯到什么。 */
function ArtifactView({ artifact }: { readonly artifact: AdminReflectionDetail['artifacts'][number] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] text-content-faint">
        产物（第 {artifact.attempt} 次尝试，契约 {artifact.output_contract.kind}）
      </span>
      <PrivateText label="产物内容" text={JSON.stringify(artifact.payload, null, 2)} />
      <PrivateText label="审核记录" text={JSON.stringify(artifact.audit, null, 2)} />
      <PrivateText
        label={'证据 ' + artifact.evidence_refs.length + ' 条'}
        text={JSON.stringify(artifact.evidence_refs, null, 2)}
      />
    </div>
  );
}

/**
 * 节点输入。
 *
 * 依赖未完成或节点未激活时后端返回 input_ready 为假且 input 为空。这不是「输入
 * 是空的」而是「输入还没形成」，因此界面按未具备呈现，不显示一个空输入框。
 */
function NodeInputView({ state }: { readonly state: ReturnType<typeof useAdminNodeInput> }) {
  return (
    <AdminListState isPending={state.isPending} error={state.error} isEmpty={false} emptyText="">
      {state.data === undefined ? null : state.data.input_ready ? (
        <PrivateText label="节点输入" text={JSON.stringify(state.data.input, null, 2)} />
      ) : (
        <p className="text-[12px] text-content-faint">
          输入尚未具备：依赖未完成或节点未激活，这里没有可以查看的输入。
        </p>
      )}
    </AdminListState>
  );
}
/** 审核结果与实际写入的事实。 */
function ResultView({ detail }: { readonly detail: AdminReflectionDetail }) {
  const result = detail.result;
  const facts = detail.facts;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] text-content-faint">审核与事实</span>
      <div className="flex flex-col">
        <FieldRow label="审核状态">
          {result === null || result === undefined ? '尚未提交审核' : result.status}
        </FieldRow>
        <FieldRow label="决定码">{result?.decision_code ?? '—'}</FieldRow>
        <FieldRow label="决定时间">
          <TimeCell value={result?.decided_at_utc} />
        </FieldRow>
        <FieldRow label="写入事实">{factText(facts)}</FieldRow>
      </div>
      {result === null || result === undefined ? null : (
        <PrivateText label="提案内容" text={JSON.stringify(result.proposal, null, 2)} />
      )}
    </div>
  );
}

/**
 * 写入的事实。
 *
 * facts 是一组已写入的对象，键结构随图类型变化。列表只给数量与各类别的出现
 * 次数，正文按需展开——事实正文可能很长，铺在这里会把审核结论挤下去。
 */
function factText(facts: AdminReflectionDetail['facts']): string {
  if (facts === null || facts === undefined || facts.length === 0) return '没有写入事实';
  const kinds = new Map<string, number>();
  for (const fact of facts) {
    const kind = 'fact_kind' in fact && typeof fact.fact_kind === 'string' ? fact.fact_kind : '其他';
    kinds.set(kind, (kinds.get(kind) ?? 0) + 1);
  }
  return [...kinds].map(([kind, count]) => `${kind} ${count} 条`).join('，');
}

/** 来源范围是本次冻结的来源集合，逐条列出便于核对边界。 */
function sourceText(graph: Graph): string {
  const sources = graph.source_scope?.sources ?? [];
  if (sources.length === 0) return '没有来源';
  return sources.map((source) => `${source.kind}:${source.ref}`).join('，');
}
