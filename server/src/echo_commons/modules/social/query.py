from dataclasses import dataclass

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.conversations.contracts import ConversationReader, MessageReader
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.modules.social.domain import ParticipationDecision, SocialChain, SocialTurn
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class VisibleTurn:
    turn: SocialTurn
    participation: tuple[ParticipationDecision, ...]
    input_message_ids: tuple[str, ...]
    chain: SocialChain | None = None


class TurnQuery:
    def __init__(
        self,
        database: Database,
        conversations: ConversationReader,
        messages: MessageReader,
        perspective: PerspectiveReader,
        social: SocialRepository,
    ) -> None:
        self.database, self.conversations, self.messages = database, conversations, messages
        self.perspective, self.social = perspective, social

    def read(
        self,
        community_id: str,
        conversation_id: str,
        player_id: str,
        *,
        limit: int = 50,
    ) -> tuple[VisibleTurn, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("Turn limit must be between 1 and 200")
        with self.database.read() as connection:
            conversation = self.conversations.get(connection, community_id, conversation_id)
            scope = ObservationScope(
                community_id,
                conversation_id,
                ActorRef("player", player_id),
                conversation.next_sequence - 1,
            )
            self.perspective.messages(
                connection, ObservationScope(community_id, conversation_id, scope.actor, 0)
            )
            found = []
            for turn in self.social.list(connection, community_id, conversation_id):
                sources = self.social.source_messages(connection, turn.social_turn_id)
                if not sources or not all(
                    self.perspective.visible(
                        connection, scope, self.messages.get(connection, conversation_id, source)
                    )
                    for source in sources
                ):
                    continue
                chain = self.social.chain(connection, turn.chain_id) if turn.chain_id else None
                if chain and not all(
                    self.perspective.visible(
                        connection, scope, self.messages.get(connection, conversation_id, source)
                    )
                    for source in self.social.source_messages(connection, chain.root_turn_id)
                ):
                    continue
                found.append(
                    VisibleTurn(
                        turn,
                        self.social.decisions(connection, turn.social_turn_id),
                        tuple(sources),
                        chain,
                    )
                )
                if len(found) >= limit:
                    break
            return tuple(reversed(found))
