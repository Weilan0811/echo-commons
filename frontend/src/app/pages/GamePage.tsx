import { useParams } from 'react-router';
import { Shell } from '@/components/Shell';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { GameSession } from '@/features/games/GameSession';

export function GamePage() {
  const { gameId = '' } = useParams<{ gameId: string }>();
  const { subject } = useCurrentSubject();
  return (
    <Shell section="games" list={null}>
      <GameSession
        key={JSON.stringify([subject.playerId, subject.communityId, gameId])}
        playerId={subject.playerId}
        communityId={subject.communityId}
        gameId={gameId}
      />
    </Shell>
  );
}
