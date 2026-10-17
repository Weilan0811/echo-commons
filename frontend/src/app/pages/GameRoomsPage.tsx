import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { ArrowLeft, ArrowUpRight, Check, CircleHelp, Plus, RefreshCw } from 'lucide-react';
import { Shell } from '@/components/Shell';
import { ErrorNotice } from '@/components/ErrorNotice';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { useCommunityMembers } from '@/api/directory';
import {
  gameStatusLabels,
  useGameList,
  useGameTypes,
  type GameStatus,
  type GameType,
} from '@/api/games';
import { memberFor, playerName, playerCountLabel } from '@/features/games/presentation';
import { gameSceneFor } from '@/features/games/sceneRegistry';
import { usePendingGameOperation } from '@/features/games/pendingOperation';
import { OperationNotice } from '@/features/games/OperationNotice';

export function GameRoomsPage() {
  const { gameType = '' } = useParams<{ gameType: string }>();
  const { subject } = useCurrentSubject();
  const types = useGameTypes();
  const selected = types.data?.items.find((game) => game.game_type === gameType);
  return (
    <Shell section="games" list={null}>
      {types.error ? (
        <div className="game-access">
          <ErrorNotice error={types.error} onRetry={() => void types.refetch()} />
        </div>
      ) : types.isPending ? (
        <p role="status" className="game-access">
          正在读取游戏…
        </p>
      ) : !selected || !gameSceneFor(selected.game_type) ? (
        <div className="game-access">
          <h1>未找到这个游戏</h1>
          <Link to="/app/games" className="game-text-button">
            <ArrowLeft size={16} />
            返回游戏大厅
          </Link>
        </div>
      ) : (
        <GameRooms
          key={JSON.stringify([subject.playerId, subject.communityId, selected.game_type])}
          game={selected}
        />
      )}
    </Shell>
  );
}

function GameRooms({ game }: { game: GameType }) {
  const { subject } = useCurrentSubject();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<GameStatus | ''>('');
  const [rulesOpen, setRulesOpen] = useState(false);
  const rooms = useGameList(subject.playerId, subject.communityId, game.game_type, filter);
  const members = useCommunityMembers(subject.playerId, subject.communityId);
  const create = usePendingGameOperation(
    subject.playerId,
    subject.communityId ?? '',
    `create:${game.game_type}`,
    !!subject.playerId && !!subject.communityId,
  );
  const players = members.data?.items ?? [];
  const presentation = gameSceneFor(game.game_type)!;
  const items = rooms.data?.pages.flatMap((page) => page.items) ?? [];
  const ready = !!subject.playerId && !!subject.communityId;
  useEffect(() => {
    if (create.result) void navigate(`/app/games/${create.result.game_id}`);
  }, [create.result, navigate]);
  function createRoom() {
    if (!subject.communityId) return;
    create.submit({
      kind: 'create',
      communityId: subject.communityId,
      participationId: null,
      body: {
        ...presentation.createInput(),
        player_id: subject.playerId,
        community_id: subject.communityId,
        request_id: crypto.randomUUID(),
      },
    });
  }
  return (
    <div className="game-lobby game-space game-room-list">
      <Link to="/app/games" className="game-text-button game-back-link">
        <ArrowLeft size={16} />
        游戏大厅
      </Link>
      <header className="game-lobby-heading">
        <div>
          <h1>{game.display_name}</h1>
          <p className="game-list-description">
            {playerCountLabel(game)} ·{' '}
            {[...new Set(game.rulesets.map((ruleset) => ruleset.display_name))].join(' · ')}
          </p>
        </div>
        <div className="game-list-actions">
          <button
            type="button"
            className="game-button game-button-quiet"
            onClick={() => setRulesOpen(!rulesOpen)}
            aria-expanded={rulesOpen}
          >
            <CircleHelp size={16} />
            规则
          </button>
          {ready ? (
            <button
              type="button"
              className="game-button game-button-primary"
              disabled={create.blocked}
              onClick={() => void createRoom()}
            >
              <Plus size={17} />
              {create.blocked ? '正在确认…' : '创建对局'}
            </button>
          ) : (
            <Link
              className="game-button game-button-primary"
              to={subject.playerId ? '/app/communities' : '/app/identity'}
            >
              {subject.playerId ? '选择社群' : '登记身份'}
            </Link>
          )}
        </div>
      </header>
      {rulesOpen ? (
        <section className="game-rule-panel" aria-label={`${game.display_name}规则`}>
          <h2>规则</h2>
          <p>{presentation.rules}</p>
        </section>
      ) : null}
      <OperationNotice operation={create} />
      <section className="game-rooms" aria-labelledby="game-rooms-title">
        <div className="game-room-toolbar">
          <h2 id="game-rooms-title">对局</h2>
          {ready ? (
            <div className="game-room-filters">
              <select
                aria-label="筛选对局状态"
                value={filter}
                onChange={(event) => setFilter(event.target.value as GameStatus | '')}
              >
                <option value="">全部对局</option>
                {Object.entries(gameStatusLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label="刷新对局"
                className="game-icon-button"
                disabled={rooms.isFetching}
                onClick={() => void rooms.refetch()}
              >
                <RefreshCw size={16} className={rooms.isFetching ? 'animate-spin' : ''} />
              </button>
            </div>
          ) : null}
        </div>
        {!ready ? (
          <p className="game-empty">
            {subject.playerId ? '请先选择社群，才能查看或创建对局。' : '请先登记身份，再选择社群。'}
          </p>
        ) : rooms.error ? (
          <ErrorNotice error={rooms.error} onRetry={() => void rooms.refetch()} />
        ) : rooms.isPending ? (
          <p role="status" className="game-empty">
            正在读取对局…
          </p>
        ) : items.length ? (
          <div className="game-room-grid">
            {items.map((room) => {
              const seated = room.game.seats.flatMap((seat) =>
                seat.occupant ? [seat.occupant] : [],
              );
              return (
                <Link
                  key={room.game.game_id}
                  to={`/app/games/${room.game.game_id}`}
                  className="game-room-card"
                >
                  <div className="game-room-card-top">
                    <span className={`game-status game-status-${room.game.status}`}>
                      {gameStatusLabels[room.game.status]}
                    </span>
                    <span className="game-room-code">
                      {room.game.game_id.slice(-4).toUpperCase()}
                    </span>
                  </div>
                  <h3>{playerName(room.game.creator_ref, players)}创建的对局</h3>
                  <div className="game-room-people">
                    <div className="game-room-avatars">
                      {seated.map((participant) => (
                        <CharacterAvatar
                          key={participant.participation_id}
                          identity={participant.participant_ref}
                          name={playerName(participant.participant_ref, players)}
                          imageUrl={memberFor(participant.participant_ref, players)?.avatar_url}
                          size="sm"
                        />
                      ))}
                    </div>
                    <p>
                      {seated
                        .map((participant) => playerName(participant.participant_ref, players))
                        .join('、')}
                    </p>
                  </div>
                  <div className="game-room-card-footer">
                    <span>
                      {seated.length} / {room.game.seats.length} 人
                      {room.conversation.status === 'archived' ? (
                        <>
                          <Check size={12} />
                          活动已结束
                        </>
                      ) : null}
                    </span>
                    <span>
                      {room.self_participation_id ? '返回对局' : '进入对局'}
                      <ArrowUpRight size={15} />
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        ) : (
          <p className="game-empty">
            {filter ? '当前筛选下没有对局' : '暂无对局，可点击“创建对局”开始。'}
          </p>
        )}
        {rooms.hasNextPage ? (
          <button
            type="button"
            className="game-button game-load-more"
            disabled={rooms.isFetchingNextPage}
            onClick={() => void rooms.fetchNextPage()}
          >
            {rooms.isFetchingNextPage ? '正在读取…' : '加载更多对局'}
          </button>
        ) : null}
      </section>
    </div>
  );
}
