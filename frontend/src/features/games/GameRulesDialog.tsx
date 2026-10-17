import * as Dialog from '@radix-ui/react-dialog';
import { CircleHelp, X } from 'lucide-react';

export function GameRulesDialog({ rules }: { rules: string }) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="game-rules-help"
          aria-label="规则与说明"
          title="规则与说明"
        >
          <CircleHelp size={16} />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" />
        <Dialog.Content className="game-rules-dialog fixed left-1/2 top-1/2 z-[61] max-h-[85dvh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-border-strong bg-surface p-6 text-content shadow-2xl">
          <Dialog.Title className="display-title pr-8 text-xl">规则与说明</Dialog.Title>
          <Dialog.Close
            className="game-icon-button absolute right-2 top-2"
            aria-label="关闭规则说明"
          >
            <X size={18} />
          </Dialog.Close>
          <Dialog.Description className="mt-4 text-sm leading-7 text-content-muted">
            {rules}
          </Dialog.Description>
          <dl className="mt-5 space-y-3 text-xs leading-6 text-content-muted">
            <div>
              <dt className="font-medium text-content">离开与认输</dt>
              <dd>
                开始前可以离开席位，创建者离开会取消对局并结束活动。开始后通过认输结束自己的比赛。关闭页面或返回列表会保留参与状态。
              </dd>
            </div>
            <div>
              <dt className="font-medium text-content">取消与结束活动</dt>
              <dd>
                取消对局后停止落子和聊天。正常结算后仍可聊天；结束活动后保留棋盘、结果和聊天记录，停止所有操作。
              </dd>
            </div>
          </dl>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
