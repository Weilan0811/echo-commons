import { RefreshCw } from 'lucide-react';
import { operationErrorMessage, type usePendingGameOperation } from './pendingOperation';

export function OperationNotice({
  operation,
}: {
  operation: ReturnType<typeof usePendingGameOperation>;
}) {
  if (!operation.pending && !operation.error) return null;
  return (
    <div className="game-operation-notice" role={operation.error ? 'alert' : 'status'}>
      <div>
        {operation.pending ? (
          <p>{operation.isSending ? '正在确认操作结果…' : '操作结果尚未确认'}</p>
        ) : null}
        {operation.error ? (
          <p className="text-warn">
            {operation.pending
              ? '连接中断或服务暂时不可用，原操作已保留。'
              : operationErrorMessage(operation.error)}
          </p>
        ) : null}
      </div>
      {operation.pending && !operation.isSending ? (
        <button className="game-button game-button-quiet" onClick={operation.recover}>
          <RefreshCw size={15} />
          重新确认
        </button>
      ) : null}
    </div>
  );
}
