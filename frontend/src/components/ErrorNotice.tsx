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
      className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      <p className="font-medium">{errorMessage(error)}</p>
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
