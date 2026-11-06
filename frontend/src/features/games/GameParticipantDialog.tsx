import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { UserPlus, X } from 'lucide-react';
import {
  useGameCharacterCandidates,
  type GameSession,
  type PendingGameOperation,
} from '@/api/games';
import type { PublicDisplay } from '@/api/directory';
import type { SchemaOf } from '@/api/http';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { memberFor, playerName, characterParticipationLabels, seatStyle } from './presentation';
import { inviteCharacterOperation, withdrawCharacterOperation } from './operations';

export function GameParticipantDialog({
  session,
  playerId,
  seatId,
  occupant,
  members,
  blocked,
  onOperation,
}: {
  session: GameSession;
  playerId: string;
  seatId: string;
  occupant: SchemaOf<'Participation'> | null;
  members: readonly PublicDisplay[];
  blocked: boolean;
  onOperation: (operation: PendingGameOperation) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const withdrawing = occupant !== null;
  const allowed = withdrawing
    ? session.capabilities.removable_participation_ids.includes(occupant.participation_id)
    : session.capabilities.can_invite;
  const candidates = useGameCharacterCandidates(playerId, session, open && !withdrawing);
  const items = candidates.data?.pages.flatMap((page) => page.items) ?? [];
  const chosen = items.find((item) => item.character_id === selected && item.eligible);
  const name = playerName(occupant?.participant_ref, members);
  if (!allowed && !open) return null;
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (!value) setSelected(null);
      }}
    >
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="game-participant-trigger"
          disabled={blocked || !allowed}
          aria-label={withdrawing ? `撤回${name}` : `邀请角色${seatStyle(session.game.game_type, seatId).label}`}
        >
          {!withdrawing ? <UserPlus size={14} /> : null}
          {withdrawing ? '撤回' : '邀请角色'}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" />
        <Dialog.Content className="game-participant-dialog fixed left-1/2 top-1/2 z-[61] max-h-[85dvh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-border-strong bg-surface p-6 text-content shadow-2xl">
          <Dialog.Title className="display-title pr-8 text-xl">
            {withdrawing ? `撤回${name}？` : '邀请角色'}
          </Dialog.Title>
          <Dialog.Close
            className="game-icon-button absolute right-2 top-2"
            aria-label="关闭角色窗口"
          >
            <X size={18} />
          </Dialog.Close>
          <Dialog.Description className="mt-3 text-sm leading-7 text-content-muted">
            {withdrawing
              ? '角色会退出席位和局内聊天。对局开始前可以重新邀请。'
              : '选择本社群的角色入座。角色可以参与局内交流，五子棋和飞行棋支持自动行动。'}
          </Dialog.Description>
          {!withdrawing ? (
            <div className="mt-5">
              {candidates.error ? (
                <ErrorNotice error={candidates.error} onRetry={() => void candidates.refetch()} />
              ) : null}
              {candidates.isPending ? (
                <p role="status" className="text-sm text-content-muted">
                  正在读取角色…
                </p>
              ) : null}
              {!candidates.isPending && !candidates.error && items.length === 0 ? (
                <p className="py-4 text-sm text-content-muted">本社群还没有角色。</p>
              ) : null}
              <div role="radiogroup" aria-label="选择角色" className="game-character-candidates">
                {items.map((item) => {
                  const reference = `character:${item.character_id}`;
                  const person = memberFor(reference, members);
                  const title = playerName(reference, members);
                  return (
                    <label
                      key={item.character_id}
                      data-selected={selected === item.character_id}
                      data-disabled={!item.eligible || blocked}
                      className="game-character-candidate"
                    >
                      <input
                        type="radio"
                        name={`game-character-${seatId}`}
                        className="sr-only"
                        value={item.character_id}
                        checked={selected === item.character_id}
                        disabled={!item.eligible || blocked}
                        onChange={() => setSelected(item.character_id)}
                      />
                      <CharacterAvatar
                        identity={reference}
                        name={title}
                        imageUrl={person?.avatar_url}
                        size="sm"
                      />
                      <span>
                        <strong>{title}</strong>
                        <small>
                          {item.reason ? characterParticipationLabels[item.reason] : '可以入座'}
                        </small>
                      </span>
                      <span className="game-character-choice" aria-hidden="true" />
                    </label>
                  );
                })}
              </div>
              {candidates.hasNextPage ? (
                <button
                  type="button"
                  className="game-text-button mt-4"
                  disabled={candidates.isFetching}
                  onClick={() => void candidates.fetchNextPage()}
                >
                  读取更多角色
                </button>
              ) : null}
            </div>
          ) : null}
          {!allowed ? (
            <p role="status" className="mt-4 text-sm text-warn">
              席位或操作资格已经变化，请关闭窗口查看当前对局。
            </p>
          ) : null}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className="game-button game-button-quiet">取消</Dialog.Close>
            <button
              type="button"
              className="game-button game-button-primary"
              disabled={blocked || !allowed || (!withdrawing && (!chosen || !!candidates.error))}
              onClick={() => {
                if (blocked || !allowed) return;
                if (occupant)
                  onOperation(
                    withdrawCharacterOperation(session, playerId, occupant.participation_id),
                  );
                else if (chosen)
                  onOperation(
                    inviteCharacterOperation(session, playerId, seatId, chosen.character_id),
                  );
                else return;
                setOpen(false);
                setSelected(null);
              }}
            >
              {withdrawing ? '确认撤回' : '邀请入座'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
