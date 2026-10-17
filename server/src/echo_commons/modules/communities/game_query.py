import sqlite3
from dataclasses import dataclass

from echo_games.public import (
    GameError,
    GameListQuery,
    GameReadAccess,
    GameService,
    GameStatus,
    GameSummary,
    Participation,
    SeatAccess,
)

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.activities.contracts import (
    CharacterParticipationReason,
    GameParticipantContext,
)
from echo_commons.modules.activities.eligibility import CharacterGameEligibility
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.game_identity import participant_actor, participant_ref
from echo_commons.modules.communities.game_participation_repository import (
    GameParticipationRepository,
)
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.conversations.domain.conversation import Conversation
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import InvalidCursor, NotFoundError
from echo_commons.shared.management import (
    PageOptions,
    decode_page_cursor,
    encode_page_cursor,
    read_page,
)


@dataclass(frozen=True)
class GameCapabilities:
    can_join: bool
    can_leave: bool
    can_start: bool
    can_resign: bool
    can_cancel: bool
    can_end: bool
    can_invite: bool
    removable_participation_ids: tuple[str, ...]
    start_blocked_reason: CharacterParticipationReason | None


@dataclass(frozen=True)
class GameSessionView:
    community_id: str
    game: GameSummary
    conversation: Conversation
    self_participations: tuple[Participation, ...]
    self_participation_id: str | None
    capabilities: GameCapabilities


class GameSessionQuery:
    def __init__(
        self,
        database: Database,
        communities: CommunityReader,
        conversations: ConversationReader,
        games: GameService,
        character_eligibility: CharacterGameEligibility,
    ) -> None:
        self.database, self.communities = database, communities
        self.conversations, self.games = conversations, games
        self.repository = GameParticipationRepository()
        self.character_eligibility = character_eligibility

    def context(self, connection, requester: ActorRef, game_id: str):
        association = self.repository.association(connection, game_id)
        self.communities.require_member(connection, association["community_id"], requester)
        game = self.games.read_game(
            connection, GameReadAccess(game_id=game_id, requester_ref=participant_ref(requester))
        )
        return association, game

    def snapshot(self, connection, requester: ActorRef, association, game) -> GameSessionView:
        conversation = self.conversations.get(
            connection, association["community_id"], association["conversation_id"]
        )
        own = self.games.find_participations(
            connection, (participant_ref(requester),), (game.game_id,)
        )
        current = next((item for item in own if item.left_at_utc is None), None)
        active, waiting = conversation.status == "active", game.status is GameStatus.WAITING
        running, creator = (
            game.status is GameStatus.RUNNING,
            game.creator_ref == participant_ref(requester),
        )
        occupants = tuple(seat.occupant for seat in game.seats if seat.occupant is not None)
        definition = self.games.registry.resolve(
            game.game_type, game.ruleset_id, game.ruleset_version
        )
        ready = definition.min_players <= len(occupants) <= definition.max_players
        blocked_reason = None
        if ready:
            actors = {participant_actor(item.participant_ref) for item in occupants}
            members = self.conversations.members(connection, conversation.conversation_id)
            ready = {member.actor for member in members} == actors
            for actor in actors:
                try:
                    self.communities.require_member(connection, association["community_id"], actor)
                    if actor.kind is ActorKind.CHARACTER:
                        reason = self.character_eligibility.reason(
                            connection, association["community_id"], actor, game
                        )
                        if reason is not None:
                            ready = False
                            blocked_reason = reason
                except NotFoundError:
                    ready = False
        return GameSessionView(
            association["community_id"],
            game,
            conversation,
            own,
            None if current is None else current.participation_id,
            GameCapabilities(
                can_join=active
                and waiting
                and current is None
                and len(occupants) < len(game.seats),
                can_leave=active and waiting and current is not None,
                can_start=active and waiting and creator and ready,
                can_resign=active and running and current is not None,
                can_cancel=active and creator and (waiting or running),
                can_end=active and creator,
                start_blocked_reason=blocked_reason,
                can_invite=active and waiting and creator and len(occupants) < len(game.seats),
                removable_participation_ids=tuple(
                    p.participation_id
                    for p in occupants
                    if active
                    and waiting
                    and creator
                    and participant_actor(p.participant_ref).kind is ActorKind.CHARACTER
                    and p.invited_by_ref == game.creator_ref
                ),
            ),
        )

    def read(self, requester: ActorRef, game_id: str) -> GameSessionView:
        with self.database.read() as connection:
            association, game = self.context(connection, requester, game_id)
            return self.snapshot(connection, requester, association, game)

    def candidates(self, requester: ActorRef, game_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            association, game = self.context(connection, requester, game_id)
            session = self.snapshot(connection, requester, association, game)
            if not session.capabilities.can_invite:
                raise GameError(
                    "operation_forbidden", "Only the creator can invite into an empty seat"
                )
            community_id = association["community_id"]
            page = read_page(
                connection,
                "SELECT actor_id AS character_id FROM community_members "
                "WHERE community_id=? AND actor_kind='character'",
                (community_id,),
                scope={
                    "query": "game_character_candidates",
                    "player_id": requester.actor_id,
                    "community_id": community_id,
                    "game_id": game_id,
                },
                order=("character_id",),
                options=options,
            )
            occupied = {seat.occupant.participant_ref for seat in game.seats if seat.occupant}
            for item in page["items"]:
                actor = ActorRef("character", item["character_id"])
                reason = self.character_eligibility.reason(connection, community_id, actor, game)
                if participant_ref(actor) in occupied:
                    reason = "already_seated"
                item.update(eligible=reason is None, reason=reason)
            return page

    def participations(
        self, connection, community_id: str, actor: ActorRef
    ) -> tuple[Participation, ...]:
        self.communities.require_member(connection, community_id, actor)
        return self.games.find_participations(
            connection,
            (participant_ref(actor),),
            self.repository.game_ids(connection, community_id),
        )

    def participant_context(
        self,
        connection,
        community_id: str,
        actor: ActorRef,
        game_id: str,
        participation_id: str | None = None,
        *,
        current: bool = True,
    ) -> GameParticipantContext:
        association, game = self.context(connection, actor, game_id)
        if association["community_id"] != community_id:
            raise NotFoundError("Game does not belong to this community")
        access = self.access(connection, actor, game_id, participation_id, current=current)
        return GameParticipantContext(community_id, association["conversation_id"], game, access)

    def list(
        self,
        requester: ActorRef,
        community_id: str,
        options: PageOptions,
        *,
        game_type: str | None = None,
        status: GameStatus | None = None,
    ) -> dict:
        scope = {
            "query": "game_sessions",
            "player_id": requester.actor_id,
            "community_id": community_id,
            "game_type": game_type,
            "status": status,
        }
        after = ""
        if options.cursor is not None:
            after = decode_page_cursor(options.cursor, scope, 1)[0]
            if not isinstance(after, str) or not after:
                raise InvalidCursor("Invalid game list position")
        with self.database.read() as connection:
            self.communities.require_member(connection, community_id, requester)
            batch = self.games.list_games(
                connection,
                GameListQuery(
                    game_ids=self.repository.game_ids(connection, community_id),
                    game_type=game_type,
                    status=status,
                    after_game_id=after,
                    limit=options.limit,
                ),
            )
            return {
                "items": [
                    self.snapshot(
                        connection,
                        requester,
                        self.repository.association(connection, game.game_id),
                        game,
                    )
                    for game in batch.items
                ],
                "has_more": batch.has_more,
                "cursor": encode_page_cursor(scope, (batch.next_game_id,))
                if batch.has_more
                else None,
            }

    def access(
        self,
        connection: sqlite3.Connection,
        requester: ActorRef,
        game_id: str,
        participation_id: str | None = None,
        *,
        current: bool = False,
    ) -> SeatAccess:
        association, _ = self.context(connection, requester, game_id)
        own = self.games.find_participations(connection, (participant_ref(requester),), (game_id,))
        candidates = tuple(
            item
            for item in own
            if (
                (participation_id is None or item.participation_id == participation_id)
                and (not current or item.left_at_utc is None)
            )
        )
        if not candidates:
            raise NotFoundError("No permitted game participation")
        selected = next((item for item in candidates if item.left_at_utc is None), candidates[-1])
        if current:
            self.conversations.current(connection, association["conversation_id"], requester)
        return SeatAccess(
            game_id=game_id,
            seat_id=selected.seat_id,
            participant_ref=selected.participant_ref,
            participation_id=selected.participation_id,
        )

    def view(self, requester: ActorRef, game_id: str):
        with self.database.read() as connection:
            access = self.access(connection, requester, game_id, current=True)
            return self.games.read_view(connection, access)

    def decision_input(self, requester: ActorRef, game_id: str, opportunity_id: str):
        with self.database.read() as connection:
            access = self.access(connection, requester, game_id, current=True)
            return self.games.read_decision_input(connection, access, opportunity_id)

    def receipt(
        self,
        requester: ActorRef,
        game_id: str,
        request_id: str,
        participation_id: str | None = None,
    ):
        with self.database.read() as connection:
            access = self.access(connection, requester, game_id, participation_id)
            receipt = self.games.read_receipt(connection, access, request_id)
            if receipt is None:
                raise NotFoundError("Game action receipt does not exist for this participant")
            return receipt

    def events(
        self,
        requester: ActorRef,
        game_id: str,
        options: PageOptions,
        *,
        participation_id: str | None = None,
        through_state_version: int | None = None,
    ) -> dict:
        with self.database.read() as connection:
            access = self.access(connection, requester, game_id, participation_id)
            scope = {
                "query": "game_events",
                "player_id": requester.actor_id,
                "game_id": game_id,
                "participation_id": access.participation_id,
                "through_state_version": through_state_version,
            }
            after = 0
            if options.cursor is not None:
                after = decode_page_cursor(options.cursor, scope, 1)[0]
                if type(after) is not int or after < 0:
                    raise InvalidCursor("Invalid game event position")
            batch = self.games.read_events(
                connection,
                access,
                after,
                options.limit,
                through_state_version=through_state_version,
            )
            return {
                "items": batch.items,
                "has_more": batch.has_more,
                "cursor": encode_page_cursor(scope, (batch.next_sequence,)),
            }
