import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { LogOut, Play, X } from 'lucide-react';
import type { GameLifecycleKind, GameSession } from '@/api/games';

const confirmations = {
  leave: {
    title: '离开对局？',
    description: '你会退出当前席位。对局开始前可以重新加入。',
    button: '确认离开',
  },
  resign: {
    title: '确认认输？',
    description: '对方将获胜，结算后仍可继续聊天。',
    button: '确认认输',
  },
  cancel: {
    title: '取消这局游戏？',
    description: '棋局将取消，聊天记录保留，不能继续发送消息。',
    button: '确认取消对局',
  },
  end: {
    title: '结束活动？',
    description: '棋局和聊天记录保留，不能继续落子或发送消息。尚未结算的棋局会取消。',
    button: '确认结束活动',
  },
};
type ConfirmationKind = keyof typeof confirmations;

export function GameControls({
  session,
  blocked,
  onOperation,
}: {
  session: GameSession;
  blocked: boolean;
  onOperation: (kind: GameLifecycleKind) => void;
}) {
  const [confirm, setConfirm] = useState<ConfirmationKind | null>(null);
  const capabilities = session.capabilities;
  const creator =
    session.game.creator_ref ===
    session.game.seats.find(
      (seat) => seat.occupant?.participation_id === session.self_participation_id,
    )?.occupant?.participant_ref;
  const details = confirm ? confirmations[confirm] : null;
  return (
    <>
      <div className="game-controls" aria-label="对局操作">
        {capabilities.can_start ? (
          <button
            className="game-button game-button-primary"
            disabled={blocked}
            onClick={() => onOperation('start')}
          >
            <Play size={16} />
            开始对局
          </button>
        ) : null}
        {capabilities.can_leave ? (
          <button
            className="game-button game-button-quiet"
            disabled={blocked}
            onClick={() => setConfirm('leave')}
          >
            <LogOut size={16} />
            离开对局
          </button>
        ) : null}
        {capabilities.can_resign ? (
          <button
            className="game-button game-button-quiet"
            disabled={blocked}
            onClick={() => setConfirm('resign')}
          >
            认输
          </button>
        ) : null}
        {capabilities.can_cancel ? (
          <button
            className="game-button game-button-quiet"
            disabled={blocked}
            onClick={() => setConfirm('cancel')}
          >
            取消对局
          </button>
        ) : null}
        {capabilities.can_end ? (
          <button
            className="game-button game-button-quiet"
            disabled={blocked}
            onClick={() => setConfirm('end')}
          >
            结束活动
          </button>
        ) : null}
      </div>
      <Dialog.Root
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" />
          <Dialog.Content className="game-confirm-dialog fixed left-1/2 top-1/2 z-[61] w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-card border border-border-strong bg-surface p-6 text-content shadow-2xl">
            <Dialog.Close
              className="game-icon-button absolute right-2 top-2"
              aria-label="关闭确认窗口"
            >
              <X size={18} />
            </Dialog.Close>
            <Dialog.Title className="display-title pr-5 text-xl">{details?.title}</Dialog.Title>
            <Dialog.Description className="my-4 text-sm leading-7 text-content-muted">
              {confirm === 'leave' && creator
                ? '创建者离开后，本局将取消，聊天活动也会结束。'
                : details?.description}
            </Dialog.Description>
            <div className="flex flex-wrap justify-end gap-2">
              <Dialog.Close className="game-button game-button-quiet">继续留在这里</Dialog.Close>
              <button
                className="game-button game-button-primary"
                disabled={blocked || !confirm || !capabilities[`can_${confirm}`]}
                onClick={() => {
                  if (confirm && capabilities[`can_${confirm}`]) onOperation(confirm);
                  setConfirm(null);
                }}
              >
                {details?.button}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
