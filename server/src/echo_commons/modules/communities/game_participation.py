import sqlite3
from uuid import uuid4

from echo_games.public import (
    ActionReceipt,
    CancelGameCommand,
    GameError,
    GameOperationReceipt,
    GameReadAccess,
    GameService,
    GameStatus,
    GameSummary,
    JoinGameCommand,
    LeaveGameCommand,
    Participation,
    ResignGameCommand,
    SeatAccess,
    StartGameCommand,
    SubmitActionCommand,
)
from pydantic import BaseModel

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.communities.contracts import (
    CommunityReader,
    CreateGameSessionCommand,
    EndGameActivityCommand,
    GameSessionOperationResult,
    GameSessionOperationSnapshot,
    JoinGameSessionCommand,
)
from echo_commons.modules.communities.game_participation_repository import (
    GameParticipationRepository,
)
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.conversations.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationStatus,
    Membership,
)
from echo_commons.modules.conversations.services.conversation import ConversationService
from echo_commons.modules.conversations.services.events import conversation_changed
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import ConflictError


def participant_ref(actor: ActorRef) -> str:
    return f"{actor.kind.value}:{actor.actor_id}"


def participant_actor(reference: str) -> ActorRef:
    kind, identity = reference.split(":", 1)
    return ActorRef(kind, identity)


class GameParticipationService:
    def __init__(
        self,
        database: Database,
        communities: CommunityReader,
        conversations: ConversationService,
        games: GameService,
        conversation_reader: ConversationReader,
    ) -> None:
        self.database = database
        self.communities = communities
        self.conversations = conversations
        self.games = games
        self.conversation_reader = conversation_reader
        self.repository = GameParticipationRepository()

    def _requester(self, connection, community_id: str, requester: ActorRef) -> str:
        if requester.kind is not ActorKind.PLAYER:
            raise GameError("operation_forbidden", "Game participation requires a player requester")
        self.communities.require_member(connection, community_id, requester)
        return participant_ref(requester)

    def _context(
        self, connection: sqlite3.Connection, requester: ActorRef, game_id: str
    ) -> tuple[sqlite3.Row, str, GameSummary, Conversation]:
        association = self.repository.association(connection, game_id)
        reference = self._requester(connection, association["community_id"], requester)
        game = self.games.read_game(
            connection, GameReadAccess(game_id=game_id, requester_ref=reference)
        )
        conversation = self.conversation_reader.get(
            connection, association["community_id"], association["conversation_id"]
        )
        return association, reference, game, conversation

    def _restore(self, connection, row) -> GameSessionOperationResult:
        snapshot = GameSessionOperationSnapshot.model_validate_json(row["result_json"])
        receipt = None
        if snapshot.game_request_id is not None:
            receipt = self.games.read_operation(
                connection, row["requester_ref"], row["game_id"], snapshot.game_request_id
            )
        return GameSessionOperationResult(
            community_id=row["community_id"],
            game_id=row["game_id"],
            operation=row["operation"],
            conversation=snapshot.conversation,
            memberships=snapshot.memberships,
            game_receipt=receipt,
        )

    def _previous(self, connection, reference, scope, request_id, operation, command):
        row = self.repository.previous(connection, reference, scope, request_id, operation, command)
        return None if row is None else self._restore(connection, row)

    def _record(
        self,
        connection: sqlite3.Connection,
        reference: str,
        scope: str,
        request_id: str,
        community_id: str,
        game_id: str,
        operation: str,
        command: BaseModel,
        receipt: GameOperationReceipt | None,
        memberships: tuple[Membership, ...] = (),
    ) -> GameSessionOperationResult:
        association = self.repository.association(connection, game_id)
        conversation = self.conversation_reader.get(
            connection, community_id, association["conversation_id"]
        )
        snapshot = GameSessionOperationSnapshot(
            conversation=conversation,
            memberships=memberships,
            game_request_id=None if receipt is None else receipt.request_id,
        )
        self.repository.add_operation(
            connection,
            reference,
            scope,
            request_id,
            community_id,
            game_id,
            operation,
            command,
            snapshot,
        )
        if self.games.notifications is not None:
            game = self.games.read_game(
                connection, GameReadAccess(game_id=game_id, requester_ref=reference)
            )
            # 创建的关联与结束的会话结果在这里已经保存，通知与业务一起提交。
            self.games.notifications.record_changed(
                connection,
                game_id,
                game.state_version,
                () if receipt is None else receipt.event_ids,
            )
        return GameSessionOperationResult(
            community_id, game_id, operation, conversation, memberships, receipt
        )

    def _active(self, conversation: Conversation) -> None:
        if conversation.status is not ConversationStatus.ACTIVE:
            raise ConflictError("Game activity has ended")

    def _creator(self, game: GameSummary, reference: str) -> None:
        if game.creator_ref != reference:
            raise GameError("operation_forbidden", "Only the creator can manage this game")

    def _own_participation(
        self, connection, game_id: str, reference: str, participation_id: str
    ) -> Participation:
        for participation in self.games.find_participations(connection, (reference,), (game_id,)):
            if (
                participation.participation_id == participation_id
                and participation.left_at_utc is None
            ):
                return participation
        raise GameError("participation_not_found", "No current participation for this player")

    def create_game(
        self, requester: ActorRef, command: CreateGameSessionCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            reference = self._requester(connection, command.community_id, requester)
            previous = self._previous(
                connection, reference, "", command.game.request_id, "create", command
            )
            if previous is not None:
                return previous
            receipt = self.games.create_game(connection, reference, command.game)
            conversation = self.conversations.create_in(
                connection,
                command.community_id,
                ConversationKind.GAME,
                (requester,),
                conversation_id=uuid4().hex,
                player_id=requester.actor_id,
            )
            self.repository.add_association(
                connection, command.community_id, receipt.game_id, conversation.conversation_id
            )
            member = self.conversation_reader.current(
                connection, conversation.conversation_id, requester
            )
            return self._record(
                connection,
                reference,
                "",
                command.game.request_id,
                command.community_id,
                receipt.game_id,
                "create",
                command,
                receipt,
                (member,),
            )

    def join_game(
        self, requester: ActorRef, command: JoinGameSessionCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, _, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "join", command
            )
            if previous is not None:
                return previous
            self._active(conversation)
            if command.participant != requester:
                raise GameError("operation_forbidden", "Players can only join themselves")
            receipt = self.games.join_game(
                connection,
                reference,
                JoinGameCommand(
                    game_id=command.game_id,
                    request_id=command.request_id,
                    expected_state_version=command.expected_state_version,
                    participant_ref=participant_ref(command.participant),
                    seat_id=command.seat_id,
                ),
            )
            member = self.conversations.join_in(
                connection,
                association["community_id"],
                conversation.conversation_id,
                command.participant,
            )
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "join",
                command,
                receipt,
                (member,),
            )

    def leave_game(
        self, requester: ActorRef, command: LeaveGameCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, _, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "leave", command
            )
            if previous is not None:
                return previous
            self._active(conversation)
            self._own_participation(
                connection, command.game_id, reference, command.participation_id
            )
            receipt = self.games.leave_game(connection, reference, command)
            member = self.conversations.leave_in(
                connection, association["community_id"], conversation.conversation_id, requester
            )
            if receipt.status_after is GameStatus.CANCELLED:
                self.conversations.archive_in(
                    connection, association["community_id"], conversation.conversation_id
                )
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "leave",
                command,
                receipt,
                (member,),
            )

    def start_game(
        self, requester: ActorRef, command: StartGameCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, game, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "start", command
            )
            if previous is not None:
                return previous
            self._active(conversation)
            self._creator(game, reference)
            actors = {
                participant_actor(seat.occupant.participant_ref)
                for seat in game.seats
                if seat.occupant is not None
            }
            for actor in actors:
                self.communities.require_member(connection, association["community_id"], actor)
            members = self.conversation_reader.members(connection, conversation.conversation_id)
            if {member.actor for member in members} != actors:
                raise ConflictError("Game seats and conversation members disagree")
            receipt = self.games.start_game(connection, reference, command)
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "start",
                command,
                receipt,
            )

    def resign_game(
        self, requester: ActorRef, command: ResignGameCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, _, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "resign", command
            )
            if previous is not None:
                return previous
            self._active(conversation)
            self._own_participation(
                connection, command.game_id, reference, command.participation_id
            )
            receipt = self.games.resign_game(connection, reference, command)
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "resign",
                command,
                receipt,
            )

    def cancel_game(
        self, requester: ActorRef, command: CancelGameCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, _, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "cancel", command
            )
            if previous is not None:
                return previous
            self._active(conversation)
            receipt = self.games.cancel_game(connection, reference, command)
            conversation_changed(connection, conversation.conversation_id)
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "cancel",
                command,
                receipt,
            )

    def end_activity(
        self, requester: ActorRef, command: EndGameActivityCommand
    ) -> GameSessionOperationResult:
        with self.database.transaction() as connection:
            association, reference, game, conversation = self._context(
                connection, requester, command.game_id
            )
            previous = self._previous(
                connection, reference, command.game_id, command.request_id, "end", command
            )
            if previous is not None:
                return previous
            self._creator(game, reference)
            if game.state_version != command.expected_state_version:
                raise GameError("state_version_conflict", "Game version has changed")
            if conversation.state_version != command.expected_conversation_version:
                raise ConflictError("Conversation state version has changed")
            receipt = None
            if game.status in (GameStatus.WAITING, GameStatus.RUNNING):
                receipt = self.games.cancel_game(
                    connection,
                    reference,
                    CancelGameCommand(
                        game_id=command.game_id,
                        request_id=command.request_id,
                        expected_state_version=command.expected_state_version,
                        reason="activity_ended",
                    ),
                )
            self.conversations.archive_in(
                connection, association["community_id"], conversation.conversation_id
            )
            return self._record(
                connection,
                reference,
                command.game_id,
                command.request_id,
                association["community_id"],
                command.game_id,
                "end",
                command,
                receipt,
            )

    def read_operation(
        self, requester: ActorRef, game_id: str, request_id: str
    ) -> GameSessionOperationResult | None:
        with self.database.read() as connection:
            _, reference, _, _ = self._context(connection, requester, game_id)
            row = self.repository.operation(connection, reference, game_id, request_id)
            return None if row is None else self._restore(connection, row)

    def seat_access(self, connection, requester: ActorRef, game_id: str) -> SeatAccess:
        _, reference, _, conversation = self._context(connection, requester, game_id)
        self.conversation_reader.current(connection, conversation.conversation_id, requester)
        for participation in self.games.find_participations(connection, (reference,), (game_id,)):
            if participation.left_at_utc is None:
                return SeatAccess(
                    game_id=game_id,
                    seat_id=participation.seat_id,
                    participant_ref=reference,
                    participation_id=participation.participation_id,
                )
        raise GameError("participation_not_found", "Player has no current game seat")

    def submit_action(
        self, requester: ActorRef, game_id: str, command: SubmitActionCommand
    ) -> ActionReceipt:
        with self.database.transaction() as connection:
            access = self.seat_access(connection, requester, game_id)
            return self.games.submit_action(connection, access, command)

    def can_send(self, connection, community_id, conversation_id, actor: ActorRef) -> bool:
        game_id = self.repository.for_conversation(connection, community_id, conversation_id)
        game = self.games.read_game(
            connection, GameReadAccess(game_id=game_id, requester_ref=participant_ref(actor))
        )
        if game.status is GameStatus.CANCELLED:
            return False
        return any(
            participation.left_at_utc is None
            for participation in self.games.find_participations(
                connection, (participant_ref(actor),), (game_id,)
            )
        )
