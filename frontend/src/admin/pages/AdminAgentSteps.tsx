import { AdminTable, MonoCell } from '@/components/Admin';
import type { AdminAgentStep } from '@/api/admin';

type Usage = AdminAgentStep['usage_summary'];

const HEAD = 'flex items-baseline gap-2';
const TITLE = 'text-[12px] text-content';
const META = 'text-[11px] text-content-faint';
const NUM = 'tabular text-[11px] text-content-muted';
const BADGE = 'rounded border border-border-subtle px-1 py-0.5 text-[11px]';

/**
 * 逐步执行。
 *
 * 一步是一次模型往返。工具调用、耗时与诊断码都在这里，回答「模型当时做了
 * 什么」只能从这里找，产物本身只给最终结果。
 *
 * 用量显示在步骤列表之前而不是每一步：用量是整次调用的累计值，逐步记录里
 * 并不携带它，放在每步会显示成每步都是零。
 */
export function AgentSteps({ steps, usage }: { readonly steps: readonly AdminAgentStep[]; readonly usage: Usage }) {
  return (
    <div className="flex flex-col gap-2">
      <UsageLine usage={usage} />
      <ol className="flex flex-col gap-2">
        {steps.map((step) => (
          <li key={step.step_index} className="rounded-md border border-border-subtle px-2.5 py-2">
            <div className={HEAD}>
              <span className="tabular text-[11px] text-content-faint">第 {step.step_index} 步</span>
              <span className={TITLE}>{step.response_kind}</span>
              <span className={'tabular ml-auto text-[11px] text-content-muted'}>
                {step.duration_ms === null ? '—' : step.duration_ms + ' ms'}
              </span>
            </div>

            <AdminTable
              headers={['工具', '结果', '耗时', '推进']}
              rows={step.tool_activities.map((tool) => ({
                key: tool.call_id,
                cells: [
                  <MonoCell key="n">{tool.name}</MonoCell>,
                  <span key="o" className="text-[12px]">
                    {tool.ok ? (
                      <span className="text-content-faint">成功</span>
                    ) : (
                      <span className="text-danger">{tool.error_code ?? '失败'}</span>
                    )}
                  </span>,
                  <MonoCell key="d">
                    {tool.duration_ms === null ? '—' : tool.duration_ms + ' ms'}
                  </MonoCell>,
                  <MonoCell key="p">
                    {tool.progressed === true
                      ? '有推进'
                      : (tool.no_progress_streak ?? 0) > 0
                        ? '连续 ' + tool.no_progress_streak + ' 次无推进'
                        : '—'}
                  </MonoCell>,
                ],
              }))}
              emptyText="这一步没有工具调用。"
            />

            {step.diagnostic_codes.length === 0 ? null : (
              <div className="mt-1.5 flex flex-wrap items-baseline gap-1.5">
                <span className={META}>诊断码</span>
                {step.diagnostic_codes.map((code) => (
                  <span key={code} className={BADGE}>
                    {code}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** 整次调用的用量。token 细项放在 title 里，需要时悬停查看。 */
function UsageLine({ usage }: { readonly usage: Usage }) {
  if (usage === null || usage === undefined) {
    return <p className={META}>这次调用没有用量记录。</p>;
  }
  return (
    <p className={NUM}>
      模型请求 {usage.model_request_count}，工具调用 {usage.tool_call_count}，
      <span title={tokenDetail(usage)}>输出 {usage.output_tokens} tokens</span>
    </p>
  );
}

function tokenDetail(usage: NonNullable<Usage>): string {
  return (
    '输入 ' +
    usage.input_tokens +
    '，缓存读 ' +
    usage.cache_read_tokens +
    '，缓存写 ' +
    usage.cache_write_tokens +
    '，输出 ' +
    usage.output_tokens +
    '，合计 ' +
    usage.total_tokens
  );
}