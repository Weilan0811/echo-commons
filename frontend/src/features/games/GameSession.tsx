import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  MessageCircle,
  Plus,
  RefreshCw,
  Trophy,
} from 'lucide-react';
import { useGameSession, useGameView, gameStatusLabels } from '@/api/games';
import { useCommunityMembers } from '@/api/directory';
import { ApiError } from '@/api/http';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ConversationPanel } from '@/features/chat/ConversationPanel';
import { gameSceneFor } from './sceneRegistry';
import { memberFor, playerName, roomTitle, characterParticipationLabels } from './presentation';
import { usePendingGameOperation } from './pendingOperation';
import { OperationNotice } from './OperationNotice';
import { GameControls } from './GameControls';
import { GameRulesDialog } from './GameRulesDialog';
import { GameParticipantDialog } from './GameParticipantDialog';
import { actionOperation, lifecycleOperation } from './operations';

export function GameSession({
  playerId,
  communityId,
  gameId,
}: {
  playerId: string;
  communityId: string | null;
  gameId: string;
}) {
  const { set } = useCurrentSubject();
  const room = useGameSession(playerId, communityId, gameId);
  const session = room.data;
  const view = useGameView(playerId, session);
  const members = useCommunityMembers(playerId, session?.community_id ?? null);
  const operation = usePendingGameOperation(
    playerId,
    communityId ?? '',
    gameId,
    !!session && session.community_id === communityId,
  );
  const [tab, setTab] = useState<'board' | 'chat'>('board');
  const [wideChatVisible, setWideChatVisible] = useState(
    () => window.matchMedia('(min-width: 1180px)').matches,
  );
  const [unread, setUnread] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const players = members.data?.items ?? [];
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1180px)');
    const update = () => setWideChatVisible(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  if (!playerId)
    return (
      <div className="game-space game-access">
        <h1>和朋友下一局</h1>
        <p>先登记身份，再回到这张棋桌。</p>
        <Link to="/app/identity" className="game-button game-button-primary">
          登记身份
        </Link>
      </div>
    );
  if (room.error && (!session || (room.error instanceof ApiError && room.error.status === 404)))
    return (
      <div className="game-space game-access">
        <Link to="/app/games" className="game-text-button">
          <ArrowLeft size={16} />
          返回游戏大厅
        </Link>
        <ErrorNotice
          error={room.error}
          message={
            room.error instanceof ApiError && room.error.status === 404
              ? '这张棋桌不存在，或你没有所在社群的访问资格。'
              : undefined
          }
          onRetry={() => void room.refetch()}
        />
      </div>
    );
  if (!session)
    return (
      <p role="status" className="game-space game-access">
        正在走向棋桌…
      </p>
    );
  if (communityId !== session.community_id)
    return (
      <div className="game-space game-access">
        <Link to="/app/games" className="game-text-button">
          <ArrowLeft size={16} />
          返回游戏大厅
        </Link>
        <h1>这张棋桌在另一个社群</h1>
        <p>进入所属社群后，棋局和聊天会使用相同的连接。</p>
        <button
          type="button"
          className="game-button game-button-primary"
          onClick={() => set({ communityId: session.community_id, communityName: null })}
        >
          进入棋桌所在社群
        </button>
      </div>
    );
  const game = session.game;
  const started = !!view.data;
  const currentSeat = game.seats.find((seat) => seat.seat_id === view.data?.state.current_seat_id);
  const currentName = playerName(currentSeat?.occupant?.participant_ref, players);
  const winner = game.seats.find((seat) => seat.seat_id === game.result?.winner_seat_id);
  const waiting = game.status === 'waiting';
  const allSeated = game.seats.every((seat) => seat.occupant !== null);
  const finished = game.status === 'finished';
  const cancelled = game.status === 'cancelled';
  const yourTurn = !!view.data?.opportunities.length;
  const hasCharacter = game.seats.some((seat) =>
    seat.occupant?.participant_ref.startsWith('character:'),
  );
  const characterTurn = currentSeat?.occupant?.participant_ref.startsWith('character:');
  const heading = finished
    ? game.result?.winner_seat_id
      ? `${playerName(winner?.occupant?.participant_ref, players)}赢得了这一局`
      : '棋逢对手，和局收场'
    : cancelled
      ? '这一局已取消'
      : waiting
        ? allSeated
          ? session.capabilities.start_blocked_reason
            ? `角色${characterParticipationLabels[session.capabilities.start_blocked_reason]}，暂时无法开始`
            : '朋友到齐了，准备开始吧'
          : '棋盘摆好了，等朋友入座'
        : started
          ? yourTurn
            ? '轮到你落子'
            : characterTurn
              ? `轮到${currentName}，自动行动尚未接入`
              : `等${currentName}落子`
          : '棋局正在进行';
  const presentation = gameSceneFor(game.game_type);
  const Scene = presentation?.Board;
  const roomsPath = `/app/games/types/${game.game_type}`;
  const hasHistory = session.self_participations.length > 0;
  const inaccessibleBoard = !session.self_participation_id && !waiting;
  const noBoard = view.error instanceof ApiError && view.error.code === 'game_not_started';
  const canAct =
    !operation.blocked &&
    !room.error &&
    !view.error &&
    session.conversation.status === 'active' &&
    game.status === 'running' &&
    view.data?.state_version === game.state_version;
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setCopyError(false);
    } catch {
      setCopyError(true);
    }
  }
  return (
    <div className="game-session game-space">
      <header className="game-session-header">
        <div className="flex min-w-0 items-center gap-3">
          <Link to={roomsPath} className="game-icon-button" aria-label="返回对局列表">
            <ArrowLeft size={19} />
          </Link>
          <div className="min-w-0">
            <div className="game-title-meta">
              <p className="game-eyebrow">五子棋 · 自由规则</p>
              {presentation ? <GameRulesDialog rules={presentation.rules} /> : null}
            </div>
            <h1>{roomTitle(session, players)}</h1>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="刷新棋局"
            className="game-icon-button"
            onClick={() => {
              void room.refetch();
              if (view.isEnabled) void view.refetch();
            }}
          >
            <RefreshCw size={16} />
          </button>
          <button
            type="button"
            className="game-button game-button-quiet"
            onClick={() => void copyLink()}
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
            <span>{copied ? '已复制' : '邀请朋友'}</span>
          </button>
        </div>
      </header>
      {copyError ? (
        <p role="status" className="px-5 py-2 text-xs text-warn">
          未能复制，请直接分享浏览器中的房间地址。
        </p>
      ) : null}
      <OperationNotice operation={operation} />
      {room.error ? <ErrorNotice error={room.error} onRetry={() => void room.refetch()} /> : null}
      <div className="game-mobile-tabs" aria-label="棋桌视图">
        <button type="button" aria-pressed={tab === 'board'} onClick={() => setTab('board')}>
          棋盘
        </button>
        <button type="button" aria-pressed={tab === 'chat'} onClick={() => setTab('chat')}>
          聊天{unread > 0 ? <span>{unread}</span> : null}
        </button>
      </div>
      <div className="game-session-columns">
        <section
          className={`game-table ${tab === 'chat' ? 'game-table-mobile-hidden' : ''}`}
          aria-label="五子棋桌面"
        >
          <div className="game-seat-row">
            {game.seats.map((seat) => {
              const person = memberFor(seat.occupant?.participant_ref, players);
              const name = playerName(seat.occupant?.participant_ref, players);
              const active = game.status === 'running' && currentSeat?.seat_id === seat.seat_id;
              const own = seat.occupant?.participant_ref === `player:${playerId}`;
              return (
                <div
                  key={seat.seat_id}
                  className={`game-seat ${active ? 'game-seat-active' : ''} ${!seat.occupant ? 'game-seat-empty' : ''}`}
                >
                  {seat.occupant ? (
                    <CharacterAvatar
                      identity={seat.occupant.participant_ref}
                      name={name}
                      imageUrl={person?.avatar_url}
                      size="sm"
                    />
                  ) : (
                    <span className="game-seat-placeholder">
                      <Plus size={18} />
                    </span>
                  )}
                  <div className="min-w-0">
                    <p>
                      {name}
                      {own ? (
                        <span>你</span>
                      ) : seat.occupant?.participant_ref.startsWith('character:') ? (
                        <span>角色</span>
                      ) : null}
                    </p>
                    <small>
                      <i className={`game-stone-dot game-stone-${seat.seat_id}`} />
                      {seat.seat_id === 'black' ? '执黑 · 先行' : '执白'}
                      {active ? (characterTurn ? ' · 等待行动能力接入' : ' · 正在落子') : ''}
                    </small>
                  </div>
                  <div className="game-seat-actions">
                    {!seat.occupant && session.capabilities.can_join ? (
                      <button
                        type="button"
                        className="game-button game-button-primary game-seat-join"
                        disabled={operation.blocked}
                        onClick={() =>
                          operation.submit(
                            lifecycleOperation('join', session, playerId, seat.seat_id),
                          )
                        }
                      >
                        入座
                      </button>
                    ) : null}
                    <GameParticipantDialog
                      session={session}
                      playerId={playerId}
                      seatId={seat.seat_id}
                      occupant={seat.occupant}
                      members={players}
                      blocked={operation.blocked}
                      onOperation={operation.submit}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          {hasCharacter ? (
            <p className="game-character-notice">角色已入座。自动行动与局内接话尚未接入。</p>
          ) : null}
          <div className={`game-turn-banner ${finished ? 'game-result-banner' : ''}`} role="status">
            {finished ? (
              <Trophy size={18} />
            ) : (
              <span className={`game-light-dot ${waiting ? '' : 'game-light-dot-muted'}`} />
            )}
            <span>{heading}</span>
          </div>
          {view.error && !noBoard ? (
            <div className="w-full max-w-xl px-4">
              <ErrorNotice error={view.error} onRetry={() => void view.refetch()} />
            </div>
          ) : null}
          {inaccessibleBoard ? (
            <div className="game-private-board">
              <span className="game-empty-stones">● ○</span>
              <h2>
                {hasHistory
                  ? '你已离开对局'
                  : game.status === 'running'
                    ? '这一局已经开始'
                    : '这一局已结束'}
              </h2>
              <p>
                {hasHistory ? '可以查看参与期间的聊天记录。' : '棋盘与聊天仅向实际参与者开放。'}
              </p>
              <Link to={roomsPath} className="game-text-button">
                返回对局列表
                <ArrowRight size={15} />
              </Link>
            </div>
          ) : view.isPending && !waiting ? (
            <div className="game-private-board" role="status">
              正在读取棋局…
            </div>
          ) : view.error && !noBoard ? null : (
            <div className={`game-board-stage ${waiting ? 'game-board-waiting' : ''}`}>
              {Scene ? (
                <Scene
                  key={view.data?.opportunities[0]?.opportunity_id ?? 'readonly'}
                  view={view.data ?? null}
                  pending={!canAct}
                  onAction={
                    canAct && view.data
                      ? (action) => {
                          const request = actionOperation(session, view.data!, playerId, action);
                          if (request) operation.submit(request);
                        }
                      : undefined
                  }
                />
              ) : (
                <p className="game-empty">当前页面无法显示这个游戏。</p>
              )}
              {waiting ? (
                <span className="game-waiting-label">
                  {allSeated ? '棋子就位，等你们开始。' : '等一位朋友，一起开始。'}
                </span>
              ) : null}
            </div>
          )}
          <footer className="game-table-footer">
            <span>
              {view.data
                ? `${view.data.state.stones.length} 手落子`
                : waiting
                  ? '两人入座后，由创建者开始'
                  : game.status === 'running'
                    ? '正在读取局势…'
                    : '对局已结束'}
            </span>
            <span className={`game-status game-status-${game.status}`}>
              {session.conversation.status === 'archived'
                ? '活动已结束'
                : gameStatusLabels[game.status]}
            </span>
          </footer>
          <GameControls
            session={session}
            blocked={operation.blocked}
            onOperation={(kind) => operation.submit(lifecycleOperation(kind, session, playerId))}
          />
        </section>
        <aside
          className={`game-chat ${tab === 'board' ? 'game-chat-mobile-hidden' : ''}`}
          aria-label="棋桌聊天区"
        >
          {hasHistory ? (
            <ConversationPanel
              key={JSON.stringify([playerId, session.conversation.conversation_id])}
              playerId={playerId}
              conversationId={session.conversation.conversation_id}
              mode="game"
              readOnlyMessage={cancelled ? '对局已取消，聊天记录保留。' : undefined}
              visible={tab === 'chat' || wideChatVisible}
              onUnreadChange={setUnread}
            />
          ) : (
            <div className="game-chat-welcome">
              <MessageCircle size={25} strokeWidth={1.3} />
              <h2>坐下来，聊一聊。</h2>
              <p>
                入座以后，这里就是
                <br />
                你们的桌边聊天。
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
