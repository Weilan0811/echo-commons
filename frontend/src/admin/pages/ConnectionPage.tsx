import { useLiveStatus, useReadyStatus } from '@/api/health';
import { apiBaseUrl } from '@/api/http';
import { ErrorNotice } from '@/components/ErrorNotice';
import { Panel } from '@/components/Panel';
import { StatusDot } from '@/components/StatusDot';

type Tone = 'ok' | 'warn' | 'danger' | 'idle';

function toneOf(status: string): Tone {
  if (status === 'ok' || status === 'ready') return 'ok';
  if (status === 'degraded') return 'warn';
  return 'danger';
}

type RowValue = string | number | boolean;

function Row({ label, value }: { readonly label: string; readonly value: RowValue }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <span className="text-content-muted">{label}</span>
      <span className="font-mono text-xs">{typeof value === 'boolean' ? (value ? '是' : '否') : value}</span>
    </div>
  );
}

/** 后台工作进程按名称与状态列出，反映真实返回而不是汇总结论。 */
function WorkerList({ workers }: { readonly workers: Readonly<Record<string, string>> }) {
  const entries = Object.entries(workers);
  if (entries.length === 0) return <p className="text-sm text-content-muted">没有已注册的后台工作进程</p>;

  return (
    <ul className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1 text-xs sm:grid-cols-3">
      {entries.map(([name, state]) => (
        <li key={name} className="flex items-center justify-between gap-2">
          <span className="truncate font-mono text-content-muted">{name}</span>
          <span
            className={
              state === 'running'
                ? 'shrink-0 text-ok'
                : 'shrink-0 text-warn'
            }
          >
            {state}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * 连接页：验证接口地址、跨域与后端存活状态。
 * 显示真实后端状态，并提供管理端的连接诊断。
 */
export function ConnectionPage() {
  const live = useLiveStatus();
  const ready = useReadyStatus();

  return (
    <div className="flex flex-col gap-4">
      <Panel title="后端连接" description={`接口地址 ${apiBaseUrl()}`}>
        <div className="flex flex-col gap-3">
          {live.isPending ? <StatusDot tone="idle" label="正在读取存活状态…" /> : null}
          {live.isError ? (
            <ErrorNotice diagnostic error={live.error} onRetry={() => void live.refetch()} />
          ) : null}
          {live.isSuccess ? (
            <>
              <StatusDot tone={toneOf(live.data.status)} label={`存活：${live.data.status}`} />
              <div className="divide-y divide-border-subtle">
                <Row label="服务" value={live.data.service} />
                <Row label="版本" value={live.data.version} />
              </div>
            </>
          ) : null}
        </div>
      </Panel>

      <Panel title="就绪状态" description="数据库与后台工作状态，不请求模型">
        <div className="flex flex-col gap-3">
          {ready.isPending ? <StatusDot tone="idle" label="正在读取就绪状态…" /> : null}
          {ready.isError ? (
            <ErrorNotice diagnostic error={ready.error} onRetry={() => void ready.refetch()} />
          ) : null}
          {ready.isSuccess ? (
            <>
              <StatusDot tone={toneOf(ready.data.status)} label={`就绪：${ready.data.status}`} />
              <div className="divide-y divide-border-subtle">
                <Row label="数据库" value={ready.data.database} />
                <Row label="后台工作" value={ready.data.workers_enabled ? '启用' : '关闭'} />
              </div>
              <WorkerList workers={ready.data.workers} />
            </>
          ) : null}
        </div>
      </Panel>

      <p className="text-xs text-content-muted">
        当前后端没有账户认证，页面中的玩家身份为本地测试身份。
      </p>
    </div>
  );
}
