from dataclasses import dataclass

from echo_games.public import GameService, default_registry

from echo_commons.app.games.events import GameEvents
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.game_participation import GameParticipationService
from echo_commons.modules.communities.game_query import GameSessionQuery
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.conversations.services.conversation import ConversationService


@dataclass(frozen=True)
class GameComponents:
    games: GameService
    participation: GameParticipationService
    query: GameSessionQuery
    events: GameEvents


def assemble_games(
    database: Database,
    communities: CommunityReader,
    conversations: ConversationService,
    reader: ConversationReader,
) -> GameComponents:
    events = GameEvents(communities)
    games = GameService(default_registry(), notifications=events)
    participation = GameParticipationService(database, communities, conversations, games, reader)
    return GameComponents(
        games, participation, GameSessionQuery(database, communities, reader, games), events
    )
