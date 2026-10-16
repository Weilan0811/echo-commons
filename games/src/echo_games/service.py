import sqlite3
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from echo_games.contracts import (
    ActionReceipt,
    CancelGameCommand,
    CancelledResult,
    CreatedResult,
    CreateGameCommand,
    DecisionInput,
    GameCancelled,
    GameCreated,
    GameEventBatch,
    GameEventData,
    GameListQuery,
    GameOperationReceipt,
    GameReadAccess,
    GameSeat,
    GameStarted,
    GameSummary,
    GameSummaryBatch,
    GameView,
    JoinedResult,
    JoinGameCommand,
    LeaveGameCommand,
    LeftResult,
    LifecycleCommand,
    OpenOpportunity,
    OperationKind,
    OperationResult,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantResigned,
    ResignGameCommand,
    SeatAccess,
    StartedResult,
    StartGameCommand,
    SubmitActionCommand,
)
from echo_games.domain import Game, GameStatus, Participation
from echo_games.errors import GameError
from echo_games.registry import GameRegistry
from echo_games.repository import GameRepository


class GameChangeRecorder(Protocol):
    def record_changed(
        self, connection: sqlite3.Connection, game_id: str, event_ids: tuple[str, ...]
    ) -> None: ...


def require_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Game operations require a caller-owned transaction")


class GameService:
    def __init__(
        self,
        registry: GameRegistry,
        *,
        repository: GameRepository | None = None,
        notifications: GameChangeRecorder | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository if repository is not None else GameRepository(registry)
        self.notifications = notifications

    def _game(self, connection: sqlite3.Connection, game_id: str) -> Game:
        require_transaction(connection)
        game = self.repository.game(connection, game_id)
        self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        return game

    def _current(self, connection: sqlite3.Connection, game_id: str) -> tuple[Participation, ...]:
        return tuple(
            p
            for p in self.repository.participations(connection, game_id)
            if p.left_state_version is None
        )

    def _access(
        self,
        connection: sqlite3.Connection,
        access: SeatAccess,
        *,
        current: bool = False,
    ) -> Participation:
        for p in self.repository.participations(connection, access.game_id):
            if (
                p.participation_id == access.participation_id
                and p.seat_id == access.seat_id
                and p.participant_ref == access.participant_ref
            ):
                if current and p.left_state_version is not None:
                    break
                return p
        raise GameError("participation_not_found", "No matching participation")

    def _replay(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: LifecycleCommand,
        operation: OperationKind,
        game_id: str | None,
    ) -> GameOperationReceipt | None:
        require_transaction(connection)
        existing = self.repository.operation(connection, requester_ref, command.request_id, game_id)
        if existing is not None:
            body, receipt = existing
            if body != command.model_dump_json() or receipt.operation != operation:
                raise GameError("idempotency_conflict", "Request ID has different content")
            return receipt
        return None

    def _version(self, game: Game, expected: int) -> None:
        if game.state_version != expected:
            raise GameError("state_version_conflict", "Game version has changed")

    def _creator(self, game: Game, requester_ref: str) -> None:
        if requester_ref != game.creator_ref:
            raise GameError("operation_forbidden", "Only the creator can perform this operation")

    def _waiting(self, game: Game) -> None:
        if game.status is not GameStatus.WAITING:
            raise GameError("game_already_started", "Game is no longer waiting")

    def _running(self, game: Game) -> None:
        if game.status is GameStatus.WAITING:
            raise GameError("game_not_started", "Game has not started")
        if game.status is not GameStatus.RUNNING:
            raise GameError("game_finished", "Game is no longer running")

    def _advance(self, game: Game, **changes) -> Game:
        return game.model_copy(
            update={
                "state_version": game.state_version + 1,
                "updated_at_utc": datetime.now(UTC),
                **changes,
            }
        )

    def _events(
        self,
        connection: sqlite3.Connection,
        game: Game,
        data: tuple[GameEventData, ...],
        audience: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        if audience is None:
            audience = tuple(p.participation_id for p in self._current(connection, game.game_id))
        sequence = self.repository.next_sequence(connection, game.game_id)
        models = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version).models
        ids = []
        for offset, item in enumerate(data):
            event = models.event(
                event_id=uuid4().hex,
                game_id=game.game_id,
                sequence=sequence + offset,
                state_version=game.state_version,
                occurred_at_utc=game.updated_at_utc,
                type=item.type,
                data=item,
            )
            self.repository.insert_event(connection, event, audience)
            ids.append(event.event_id)
        if self.notifications is not None:
            self.notifications.record_changed(connection, game.game_id, tuple(ids))
        return tuple(ids)

    def _operation(
        self,
        connection: sqlite3.Connection,
        game: Game,
        requester_ref: str,
        command: LifecycleCommand,
        operation: OperationKind,
        before: int,
        result: OperationResult,
        event_ids: tuple[str, ...],
    ) -> GameOperationReceipt:
        models = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version).models
        receipt = models.operation_receipt(
            receipt_id=uuid4().hex,
            game_id=game.game_id,
            requester_ref=requester_ref,
            request_id=command.request_id,
            operation=operation,
            state_version_before=before,
            state_version_after=game.state_version,
            status_after=game.status,
            result=result,
            event_ids=event_ids,
            occurred_at_utc=game.updated_at_utc,
        )
        self.repository.insert_operation(connection, command.model_dump_json(), receipt)
        return receipt

    def create_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: CreateGameCommand,
    ) -> GameOperationReceipt:
        definition = self.registry.resolve(
            command.game_type, command.ruleset_id, command.ruleset_version
        )
        command = definition.models.create_command.model_validate(
            command.model_dump(mode="python", serialize_as_any=True)
        )
        replay = self._replay(connection, requester_ref, command, "create", None)
        if replay is not None:
            return replay
        if command.initial_seat_id not in definition.seat_ids:
            raise GameError("invalid_seat", "Unknown initial seat")
        now = datetime.now(UTC)
        game = definition.models.game(
            game_id=uuid4().hex,
            game_type=command.game_type,
            ruleset_id=command.ruleset_id,
            ruleset_version=command.ruleset_version,
            creator_ref=requester_ref,
            status=GameStatus.WAITING,
            state_version=1,
            config=command.config,
            created_at_utc=now,
            updated_at_utc=now,
        )
        self.repository.insert_game(connection, game, definition.seat_ids)
        participation = Participation(
            participation_id=uuid4().hex,
            game_id=game.game_id,
            seat_id=command.initial_seat_id,
            participant_ref=requester_ref,
            invited_by_ref=requester_ref,
            joined_at_utc=now,
            joined_state_version=1,
        )
        self.repository.insert_participation(connection, participation)
        events = self._events(
            connection,
            game,
            (
                GameCreated(
                    creator_ref=requester_ref,
                    game_type=game.game_type,
                    ruleset_id=game.ruleset_id,
                    ruleset_version=game.ruleset_version,
                ),
                ParticipantJoined(participation=participation),
            ),
        )
        return self._operation(
            connection,
            game,
            requester_ref,
            command,
            "create",
            0,
            CreatedResult(participation=participation),
            events,
        )

    def join_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: JoinGameCommand,
    ) -> GameOperationReceipt:
        replay = self._replay(connection, requester_ref, command, "join", command.game_id)
        if replay is not None:
            return replay
        game = self._game(connection, command.game_id)
        if requester_ref != command.participant_ref:
            self._creator(game, requester_ref)
        self._version(game, command.expected_state_version)
        self._waiting(game)
        if command.seat_id not in self.repository.seats(connection, game.game_id):
            raise GameError("invalid_seat", "Unknown seat")
        current = self._current(connection, game.game_id)
        if any(p.seat_id == command.seat_id for p in current):
            raise GameError("seat_occupied", "Seat is already occupied")
        if any(p.participant_ref == command.participant_ref for p in current):
            raise GameError("participant_already_seated", "Participant already occupies a seat")
        updated = self._advance(game)
        participation = Participation(
            participation_id=uuid4().hex,
            game_id=game.game_id,
            seat_id=command.seat_id,
            participant_ref=command.participant_ref,
            invited_by_ref=requester_ref,
            joined_at_utc=updated.updated_at_utc,
            joined_state_version=updated.state_version,
        )
        self.repository.insert_participation(connection, participation)
        self.repository.save_game(connection, updated)
        events = self._events(
            connection, updated, (ParticipantJoined(participation=participation),)
        )
        return self._operation(
            connection,
            updated,
            requester_ref,
            command,
            "join",
            game.state_version,
            JoinedResult(participation=participation),
            events,
        )

    def _managed_participation(
        self,
        connection: sqlite3.Connection,
        game: Game,
        requester_ref: str,
        participation_id: str,
    ) -> Participation:
        for p in self._current(connection, game.game_id):
            if p.participation_id == participation_id:
                if requester_ref != p.participant_ref and not (
                    requester_ref == game.creator_ref == p.invited_by_ref
                ):
                    raise GameError("operation_forbidden", "Cannot manage this participant")
                return p
        raise GameError("participation_not_found", "No current participation")

    def leave_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: LeaveGameCommand,
    ) -> GameOperationReceipt:
        replay = self._replay(connection, requester_ref, command, "leave", command.game_id)
        if replay is not None:
            return replay
        game = self._game(connection, command.game_id)
        p = self._managed_participation(connection, game, requester_ref, command.participation_id)
        self._version(game, command.expected_state_version)
        self._waiting(game)
        creator_leaving = p.participant_ref == game.creator_ref
        updated = self._advance(
            game,
            **(
                {"status": GameStatus.CANCELLED, "cancel_reason": "creator_left"}
                if creator_leaving
                else {}
            ),
        )
        audience = tuple(p.participation_id for p in self._current(connection, game.game_id))
        left = p.model_copy(
            update={
                "left_at_utc": updated.updated_at_utc,
                "left_state_version": updated.state_version,
            }
        )
        self.repository.save_participation(connection, left)
        self.repository.save_game(connection, updated)
        data: tuple[GameEventData, ...] = (
            ParticipantLeft(participation_id=p.participation_id, seat_id=p.seat_id),
        )
        if creator_leaving:
            data += (GameCancelled(reason="creator_left"),)
        events = self._events(connection, updated, data, audience)
        return self._operation(
            connection,
            updated,
            requester_ref,
            command,
            "leave",
            game.state_version,
            LeftResult(participation=left),
            events,
        )

    def _new_opportunities(self, connection: sqlite3.Connection, game: Game) -> None:
        if game.status is not GameStatus.RUNNING:
            return
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        for p in self._current(connection, game.game_id):
            if definition.legal_actions(game.state, p.seat_id):
                self.repository.add_opportunity(
                    connection,
                    OpenOpportunity(
                        opportunity_id=uuid4().hex,
                        game_id=game.game_id,
                        seat_id=p.seat_id,
                        participation_id=p.participation_id,
                        expected_state_version=game.state_version,
                        phase=definition.phase(game.state),
                    ),
                )

    def start_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: StartGameCommand,
    ) -> GameOperationReceipt:
        replay = self._replay(connection, requester_ref, command, "start", command.game_id)
        if replay is not None:
            return replay
        game = self._game(connection, command.game_id)
        self._creator(game, requester_ref)
        self._version(game, command.expected_state_version)
        self._waiting(game)
        current = self._current(connection, game.game_id)
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        if not definition.min_players <= len(current) <= definition.max_players:
            raise GameError("game_not_ready", "The game needs more participants")
        updated = self._advance(
            game, status=GameStatus.RUNNING, state=definition.initialize(game.config)
        )
        for p in current:
            self.repository.save_participation(
                connection,
                p.model_copy(
                    update={
                        "started_state_version": updated.state_version,
                    }
                ),
            )
        self.repository.save_game(connection, updated)
        self._new_opportunities(connection, updated)
        participation_ids = tuple(p.participation_id for p in current)
        events = self._events(
            connection, updated, (GameStarted(participation_ids=participation_ids),)
        )
        return self._operation(
            connection,
            updated,
            requester_ref,
            command,
            "start",
            game.state_version,
            StartedResult(participation_ids=participation_ids),
            events,
        )

    def resign_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: ResignGameCommand,
    ) -> GameOperationReceipt:
        replay = self._replay(connection, requester_ref, command, "resign", command.game_id)
        if replay is not None:
            return replay
        game = self._game(connection, command.game_id)
        p = self._managed_participation(connection, game, requester_ref, command.participation_id)
        self._version(game, command.expected_state_version)
        self._running(game)
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        state = definition.resign(game.state, p.seat_id)
        outcome = definition.outcome(state)
        if outcome is None:
            raise GameError("invalid_rule_result", "Resignation must produce a final result")
        updated = self._advance(game, status=GameStatus.FINISHED, state=state)
        self.repository.save_game(connection, updated)
        self.repository.close_opportunities(connection, game.game_id, "expired")
        events = self._events(
            connection,
            updated,
            (
                ParticipantResigned(participation_id=p.participation_id, seat_id=p.seat_id),
                definition.models.finished_event(result=outcome),
            ),
        )
        return self._operation(
            connection,
            updated,
            requester_ref,
            command,
            "resign",
            game.state_version,
            definition.models.resigned_result(participation_id=p.participation_id, result=outcome),
            events,
        )

    def cancel_game(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        command: CancelGameCommand,
    ) -> GameOperationReceipt:
        replay = self._replay(connection, requester_ref, command, "cancel", command.game_id)
        if replay is not None:
            return replay
        game = self._game(connection, command.game_id)
        self._creator(game, requester_ref)
        self._version(game, command.expected_state_version)
        if game.status not in (GameStatus.WAITING, GameStatus.RUNNING):
            raise GameError("game_finished", "Cannot cancel a finished game")
        updated = self._advance(game, status=GameStatus.CANCELLED, cancel_reason=command.reason)
        self.repository.save_game(connection, updated)
        self.repository.close_opportunities(connection, game.game_id, "expired")
        events = self._events(connection, updated, (GameCancelled(reason=command.reason),))
        return self._operation(
            connection,
            updated,
            requester_ref,
            command,
            "cancel",
            game.state_version,
            CancelledResult(reason=command.reason),
            events,
        )

    def read_game(self, connection: sqlite3.Connection, access: GameReadAccess) -> GameSummary:
        # 宿主检查所属社群的概要读取资格；私人视图必须另外使用 SeatAccess。
        game = self._game(connection, access.game_id)
        return self._summary(connection, game)

    def _summary(self, connection: sqlite3.Connection, game: Game) -> GameSummary:
        current = {p.seat_id: p for p in self._current(connection, game.game_id)}
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        return definition.models.summary(
            **game.model_dump(exclude={"state"}),
            seats=tuple(
                GameSeat(seat_id=seat, occupant=current.get(seat))
                for seat in self.repository.seats(connection, game.game_id)
            ),
            result=None if game.state is None else definition.outcome(game.state),
        )

    def list_games(self, connection: sqlite3.Connection, query: GameListQuery) -> GameSummaryBatch:
        require_transaction(connection)
        games = self.repository.list_games(connection, query)
        items = tuple(
            self._summary(connection, self._game(connection, game.game_id))
            for game in games[: query.limit]
        )
        return GameSummaryBatch(
            items=items,
            has_more=len(games) > query.limit,
            next_game_id=items[-1].game_id if items else query.after_game_id,
        )

    def find_participations(
        self,
        connection: sqlite3.Connection,
        participant_refs: tuple[str, ...],
        game_ids: tuple[str, ...],
    ) -> tuple[Participation, ...]:
        require_transaction(connection)
        return tuple(
            p
            for game_id in dict.fromkeys(game_ids)
            for p in self.repository.participations(connection, game_id)
            if p.participant_ref in participant_refs
        )

    def read_operation(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        game_id: str,
        request_id: str,
    ) -> GameOperationReceipt | None:
        require_transaction(connection)
        existing = self.repository.operation(connection, requester_ref, request_id, game_id)
        return None if existing is None else existing[1]

    def read_view(self, connection: sqlite3.Connection, access: SeatAccess) -> GameView:
        game = self._game(connection, access.game_id)
        self._access(connection, access, current=True)
        if game.state is None:
            raise GameError("game_not_started", "Game has not started")
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        opportunities = []
        for item in self.repository.open_opportunities(connection, game.game_id):
            if item.participation_id == access.participation_id:
                actions = definition.legal_actions(game.state, access.seat_id)
                opportunities.append(
                    definition.models.opportunity(
                        **item.model_dump(),
                        choice_required=len(actions) > 1,
                        legal_actions=actions,
                    )
                )
        return definition.models.view(
            game_id=game.game_id,
            game_type=game.game_type,
            ruleset_id=game.ruleset_id,
            ruleset_version=game.ruleset_version,
            state_version=game.state_version,
            status=game.status,
            phase=(
                "cancelled" if game.status is GameStatus.CANCELLED else definition.phase(game.state)
            ),
            viewer_seat_id=access.seat_id,
            viewer_participation_id=access.participation_id,
            state=definition.observe(game.state, access.seat_id),
            opportunities=tuple(opportunities),
        )

    def list_open_opportunities(
        self,
        connection: sqlite3.Connection,
        seats: tuple[SeatAccess, ...],
    ) -> tuple[OpenOpportunity, ...]:
        require_transaction(connection)
        found = {}
        for access in seats:
            self._access(connection, access, current=True)
            for item in self.repository.open_opportunities(connection, access.game_id):
                if item.participation_id == access.participation_id:
                    found[item.opportunity_id] = item
        return tuple(found.values())

    def read_decision_input(
        self,
        connection: sqlite3.Connection,
        access: SeatAccess,
        opportunity_id: str,
    ) -> DecisionInput:
        view = self.read_view(connection, access)
        for opportunity in view.opportunities:
            if opportunity.opportunity_id == opportunity_id:
                definition = self.registry.resolve(
                    view.game_type, view.ruleset_id, view.ruleset_version
                )
                return definition.models.decision_input(
                    view=view, opportunity=opportunity, instructions=definition.instructions
                )
        raise GameError("opportunity_expired", "The action opportunity is no longer available")

    def read_receipt(
        self,
        connection: sqlite3.Connection,
        access: SeatAccess,
        request_id: str,
    ) -> ActionReceipt | None:
        require_transaction(connection)
        self._access(connection, access)
        existing = self.repository.action_receipt(
            connection, access.game_id, access.seat_id, request_id
        )
        if existing is not None and (
            existing[1].participation_id == access.participation_id
            and existing[1].participant_ref == access.participant_ref
        ):
            return existing[1]
        return None

    def submit_action(
        self,
        connection: sqlite3.Connection,
        access: SeatAccess,
        command: SubmitActionCommand,
    ) -> ActionReceipt:
        game = self._game(connection, access.game_id)
        definition = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        command = definition.models.action_command.model_validate(
            command.model_dump(mode="python", serialize_as_any=True)
        )
        self._access(connection, access)
        existing = self.repository.action_receipt(
            connection, access.game_id, access.seat_id, command.request_id
        )
        if existing is not None:
            if (
                existing[0] != command.model_dump_json()
                or existing[1].participation_id != access.participation_id
                or existing[1].participant_ref != access.participant_ref
            ):
                raise GameError("idempotency_conflict", "Request ID has different content or owner")
            return existing[1]
        self._access(connection, access, current=True)
        self._running(game)
        self._version(game, command.expected_state_version)
        opportunities = self.repository.open_opportunities(connection, game.game_id)
        if not any(p.participation_id == access.participation_id for p in opportunities):
            raise GameError("not_current_actor", "This seat cannot act now")
        if not any(
            p.opportunity_id == command.opportunity_id
            and p.participation_id == access.participation_id
            for p in opportunities
        ):
            raise GameError("opportunity_expired", "The action opportunity is no longer available")
        transition = definition.apply(game.state, access.seat_id, command.action)
        state, result = transition.state, transition.result
        outcome = definition.outcome(state)
        updated = self._advance(
            game,
            state=state,
            status=(GameStatus.FINISHED if outcome is not None else GameStatus.RUNNING),
        )
        self.repository.save_game(connection, updated)
        self.repository.close_opportunities(connection, game.game_id, "consumed")
        self._new_opportunities(connection, updated)
        data: tuple[GameEventData, ...] = transition.events
        if outcome is not None:
            data += (definition.models.finished_event(result=outcome),)
        events = self._events(connection, updated, data)
        receipt = definition.models.action_receipt(
            receipt_id=uuid4().hex,
            game_id=game.game_id,
            seat_id=access.seat_id,
            participant_ref=access.participant_ref,
            participation_id=access.participation_id,
            request_id=command.request_id,
            opportunity_id=command.opportunity_id,
            state_version_before=game.state_version,
            state_version_after=updated.state_version,
            result=result,
            event_ids=events,
            occurred_at_utc=updated.updated_at_utc,
        )
        self.repository.insert_action(connection, command.model_dump_json(), receipt)
        return receipt

    def read_events(
        self,
        connection: sqlite3.Connection,
        access: SeatAccess,
        after_sequence: int = 0,
        limit: int = 50,
        *,
        through_state_version: int | None = None,
    ) -> GameEventBatch:
        game = self._game(connection, access.game_id)
        self._access(connection, access)
        if after_sequence < 0 or not 1 <= limit <= 200:
            raise ValueError("Invalid event position or limit")
        version = game.state_version if through_state_version is None else through_state_version
        if not 1 <= version <= game.state_version:
            raise ValueError("Invalid event version boundary")
        events = self.repository.events(connection, game.game_id, after_sequence, limit, version)
        scanned = events[:limit]
        visible = tuple(
            event
            for event in scanned
            if self.repository.event_visible(connection, event.event_id, access.participation_id)
        )
        models = self.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version).models
        return models.event_batch(
            items=visible,
            has_more=len(events) > limit,
            next_sequence=scanned[-1].sequence if scanned else after_sequence,
        )
