import { Link } from 'react-router';
import { ArrowRight, Users } from 'lucide-react';
import { Shell } from '@/components/Shell';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useGameTypes } from '@/api/games';
import { gameSceneFor } from '@/features/games/sceneRegistry';
import { playerCountLabel } from '@/features/games/presentation';

export function GamesPage() {
  const types = useGameTypes();
  const games = types.data?.items ?? [];
  return (
    <Shell section="games" list={null}>
      <div className="game-lobby game-space">
        <header className="game-lobby-heading">
          <h1>游戏</h1>
        </header>
        {types.error ? (
          <ErrorNotice error={types.error} onRetry={() => void types.refetch()} />
        ) : types.isPending ? (
          <p role="status" className="text-sm text-content-muted">
            正在读取游戏…
          </p>
        ) : games.length === 0 ? (
          <p className="game-empty">暂无可用游戏</p>
        ) : (
          <div className="game-catalog-grid" aria-label="游戏目录">
            {games.map((game) => {
              const presentation = gameSceneFor(game.game_type);
              if (!presentation) return null;
              const Cover = presentation.Cover;
              return (
                <Link
                  key={game.game_type}
                  to={`/app/games/types/${game.game_type}`}
                  className="game-catalog-card"
                  aria-label={`查看${game.display_name}对局`}
                >
                  <div className="game-catalog-cover" aria-hidden="true">
                    <Cover />
                  </div>
                  <div className="game-catalog-copy">
                    <h2>{game.display_name}</h2>
                    <p>{presentation.description}</p>
                    <div className="game-catalog-meta">
                      <span>
                        <Users size={14} />
                        {playerCountLabel(game)}
                      </span>
                      <span>
                        {game.rulesets
                          .map((ruleset) => ruleset.display_name)
                          .filter((name, index, names) => names.indexOf(name) === index)
                          .join(' · ')}
                      </span>
                    </div>
                    <span className="game-catalog-action">
                      查看对局
                      <ArrowRight size={16} />
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </Shell>
  );
}
