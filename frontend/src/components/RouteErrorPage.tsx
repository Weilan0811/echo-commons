import { useRouteError } from 'react-router';
import { errorMessage } from './ErrorNotice';

/**
 * 路由级错误边界：渲染失败时给出可读提示与恢复入口，
 * 不把组件内部错误直接暴露给使用者。
 */
export function RouteErrorPage() {
  const error = useRouteError();

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-4">
      <h1 className="text-lg font-semibold">页面无法显示</h1>
      <p className="mt-2 text-sm text-content-muted">
        渲染过程中出现异常。若反复出现，请把下面的信息反馈给开发者。
      </p>
      <pre className="mt-4 overflow-auto rounded border border-border-subtle bg-surface-muted p-3 text-xs">
        {errorMessage(error)}
      </pre>
      <div className="mt-4">
        <a
          href="/app"
          className="rounded border border-border-subtle px-2 py-1 text-sm hover:bg-surface-muted"
        >
          返回用户端
        </a>
      </div>
    </div>
  );
}
