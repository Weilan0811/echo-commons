import type { ReactNode } from 'react';
import { ApiError } from '@/api/http';

/** 统一的错误文案入口，页面不各自拼接错误文本。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return '发生未知错误';
}

interface ErrorNoticeProps {
  readonly error: unknown;
  readonly onRetry?: () => void;
}

/** 展示归一后的错误；422 附带字段级明细。 */
export function ErrorNotice({ error, onRetry }: ErrorNoticeProps) {
  if (error === null || error === undefined) return null;

  const fields = error instanceof ApiError ? error.fieldErrors : [];

  return (
    <div
      role="alert"
      className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
    >
      <p className="font-medium">{errorMessage(error)}</p>
      {fields.length > 0 ? (
        <ul className="mt-1 list-disc pl-5 text-danger/90">
          {fields.map((field) => (
            <li key={`${field.location.join('.')}-${field.message}`}>
              {field.location.join('.')}: {field.message}
            </li>
          ))}
        </ul>
      ) : null}
      {onRetry === undefined ? null : (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-danger/40 px-2 py-1 text-xs hover:bg-danger/10"
        >
          重试
        </button>
      )}
    </div>
  );
}

interface PanelProps {
  readonly title: string;
  readonly description?: string;
  readonly children: ReactNode;
}

/** 通用内容区块。信息密度按页面需要调整，不在此固定视觉规格。 */
export function Panel({ title, description, children }: PanelProps) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description === undefined ? null : (
          <p className="mt-0.5 text-xs text-content-muted">{description}</p>
        )}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

interface StatusDotProps {
  readonly tone: 'ok' | 'warn' | 'danger' | 'idle';
  readonly label: string;
}

export function StatusDot({ tone, label }: StatusDotProps) {
  const toneClass = {
    ok: 'bg-ok',
    warn: 'bg-warn',
    danger: 'bg-danger',
    idle: 'bg-border-subtle',
  }[tone];

  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`inline-block size-2 rounded-full ${toneClass}`} aria-hidden="true" />
      {label}
    </span>
  );
}