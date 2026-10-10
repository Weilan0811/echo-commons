import { ApiError } from '@/api/http';

/** 统一的错误文案入口，页面不各自拼接错误文本。 */
export function errorMessage(error: unknown, diagnostic = false): string {
  if (diagnostic && error instanceof Error) return error.message;
  if (error instanceof ApiError) {
    if (error.status === 0) return '暂时无法连接，请检查网络后重试。';
    if (error.status === 404) return '暂时找不到这些内容，请刷新页面。';
    if (error.status === 409) return '内容已经发生变化，请刷新后再操作。';
    if (error.status === 422 || error.status === 400) return '请检查填写内容后再试。';
    if (error.status === 503) return '服务暂时不可用，请稍后重试。';
  }
  return '操作未完成，请稍后重试。';
}

interface ErrorNoticeProps {
  readonly error: unknown;
  readonly onRetry?: () => void;
  readonly diagnostic?: boolean;
}

/** 展示归一后的错误；422 附带字段级明细。 */
export function ErrorNotice({ error, onRetry, diagnostic = false }: ErrorNoticeProps) {
  if (error === null || error === undefined) return null;

  const fields = diagnostic && error instanceof ApiError ? error.fieldErrors : [];

  return (
    <div
      role="alert"
      className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      <p className="font-medium">{errorMessage(error, diagnostic)}</p>
      {fields.length > 0 ? (
        <ul className="mt-1 list-disc pl-5 text-danger/80">
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
          className="mt-2 rounded border border-danger/40 px-2 py-1 text-xs hover:bg-danger/15"
        >
          重试
        </button>
      )}
    </div>
  );
}
