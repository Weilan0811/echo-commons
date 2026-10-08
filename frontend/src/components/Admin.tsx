import { useState, type ReactNode } from 'react';
import { ErrorNotice } from './ErrorNotice';

/** 展开后才挂载详情，避免列表自动读取每一项的私有内容。 */
export function AdminDisclosure({ summary, children }: {
  readonly summary: ReactNode;
  readonly children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-2">{summary}</summary>
      {open ? children : null}
    </details>
  );
}

/**
 * 管理页的区块。
 *
 * 管理端按对象组织而不是按表单组织：一个社群下面挂着成员、角色、会话和任务，
 * 它们是并列的诊断视图。区块只负责标题与间距，不引入卡片边框——诊断页面
 * 的信息密度高，层层描边会把结构吃掉。
 */
export function AdminSection({
  title,
  count,
  children,
  actions,
}: {
  readonly title: string;
  readonly count?: number;
  readonly children: ReactNode;
  readonly actions?: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border-subtle pb-2">
        <h2 className="text-[12px] font-semibold uppercase tracking-widest text-content-muted">
          {title}
          {count === undefined ? null : <span className="tabular ml-2 text-content-faint">{count}</span>}
        </h2>
        {actions}
      </div>
      <div className="min-w-0 pt-2">{children}</div>
    </section>
  );
}

/** 键值对。管理端大量字段是只读事实，成对呈现比逐行手写标签清晰。 */
export function FieldRow({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 py-1">
      <span className="w-28 shrink-0 text-[11px] text-content-faint">{label}</span>
      <span className="tabular min-w-0 flex-1 break-words text-[12px]">{children}</span>
    </div>
  );
}

/** 状态徽标。按已知状态给颜色，未知状态按中性显示，不猜它意味着什么。 */
export function StatusBadge({ value }: { readonly value: string }) {
  const tone =
    value === 'completed' || value === 'active' || value === 'available' || value === 'ready'
      ? 'text-ok'
      : value === 'failed' || value === 'cancelled'
        ? 'text-danger'
        : value === 'running' || value === 'processing' || value === 'retry_wait'
          ? 'text-warn'
          : 'text-content-faint';
  return (
    <span className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ${tone}`}>
      {value}
    </span>
  );
}

/** 私有正文块。管理接口返回的角色内心与冻结输入默认折叠，按需展开。 */
export function PrivateText({
  label,
  text,
  removed,
}: {
  readonly label: string;
  readonly text: string | null | undefined;
  readonly removed?: boolean;
}) {
  return (
    <details className="rounded-lg border border-border-subtle bg-surface-sunken/50 px-3 py-2">
      <summary className="cursor-pointer text-[11px] text-content-muted">{label}</summary>
      <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed">
        {text === null || text === undefined || text === '' ? (
          <span className="text-content-faint">
            {removed === true ? '正文已清除，保留来源编号。' : '没有正文。'}
          </span>
        ) : (
          text
        )}
      </p>
    </details>
  );
}

/** 列表读取状态。三种状态说清楚，不让「空」和「失败」看起来一样。 */
export function AdminListState({
  isPending,
  error,
  isEmpty,
  emptyText,
  children,
}: {
  readonly isPending: boolean;
  readonly error: unknown;
  readonly isEmpty: boolean;
  readonly emptyText: string;
  readonly children: ReactNode;
}) {
  if (error !== null && error !== undefined) return <ErrorNotice error={error} />;
  if (isPending) return <p className="py-3 text-[12px] text-content-faint">正在读取…</p>;
  if (isEmpty) return <p className="py-3 text-[12px] text-content-faint">{emptyText}</p>;
  return <>{children}</>;
}
/** 管理页外框。标题、说明与左右留白，诊断页面共用。 */
export function AdminPage({
  title,
  subtitle,
  children,
}: {
  readonly title: string;
  readonly subtitle: string;
  readonly children: ReactNode;
}) {
  return (
    <>
      <header className="px-8 pb-4 pt-6">
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 text-[12px] leading-relaxed text-content-faint">{subtitle}</p>
      </header>
      <div className="flex flex-col gap-8 px-8 pb-12">{children}</div>
    </>
  );
}
/**
 * 诊断表格。
 *
 * 管理端有七八张结构相同的表。逐张手写 table 样板会让列宽与间距各自漂移，
 * 读起来像几张不同的页面。这里统一表头、行与空状态，单元格只提供内容。
 */
export function AdminTable({
  headers,
  rows,
  emptyText,
}: {
  readonly headers: readonly string[];
  readonly rows: ReadonlyArray<{ readonly key: string; readonly cells: readonly ReactNode[] }>;
  /** 空表说明。空列表和无数据在排障时含义不同，因此由调用方给出一句解释。 */
  readonly emptyText?: string;
}) {
  if (rows.length === 0 && emptyText !== undefined) {
    return <p className="py-2 text-[12px] text-content-faint">{emptyText}</p>;
  }
  return (
    <table className="w-full">
      <thead>
        <tr className="text-left text-[11px] text-content-faint">
          {headers.map((header) => (
            <th key={header} className="py-1.5 pr-3 font-normal last:pr-0">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-t border-border-subtle/60">
            {row.cells.map((cell, index) => (
              <td key={index} className="py-1.5 pr-3 align-top last:pr-0">
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 单元格里的标识列。等宽数字，诊断时靠它对齐查找。 */
export function MonoCell({ children }: { readonly children: ReactNode }) {
  return <span className="tabular text-[12px] text-content-muted">{children}</span>;
}

/** 单元格里的时间。管理端显示带 T 的原始形式，避免误读成世界时间。 */
export function TimeCell({ value }: { readonly value: string | null | undefined }) {
  return (
    <span className="tabular text-[12px] text-content-muted">
      {value === null || value === undefined ? '—' : value.replace('T', ' ').slice(0, 19)}
    </span>
  );
}
