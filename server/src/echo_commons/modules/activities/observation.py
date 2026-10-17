import json

from echo_games.public import GameError, GameEventBatch, GameService, Participation

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.activities.contracts import (
    CharacterGameObservation,
    GameParticipationReader,
)
from echo_commons.modules.activities.eligibility import CharacterGameEligibility
from echo_commons.modules.perspective.contracts import ActivityObservation
from echo_commons.shared.actors import ActorRef


class GameObservationService:
    def __init__(
        self,
        database: Database,
        games: GameService,
        participation: GameParticipationReader,
        eligibility: CharacterGameEligibility,
    ) -> None:
        self.database, self.games = database, games
        self.participation, self.eligibility = participation, eligibility

    def participations(self, community_id: str, character_id: str) -> tuple[Participation, ...]:
        with self.database.read() as connection:
            return self.participation.participations(
                connection, community_id, ActorRef("character", character_id)
            )

    def observe(
        self,
        community_id: str,
        character_id: str,
        game_id: str,
        *,
        participation_id: str | None = None,
        after_sequence: int = 0,
        limit: int = 50,
    ) -> CharacterGameObservation:
        actor = ActorRef("character", character_id)
        with self.database.read() as connection:
            context = self.participation.participant_context(
                connection,
                community_id,
                actor,
                game_id,
                participation_id,
            )
            game, access = context.game, context.access
            self.eligibility.require(connection, community_id, actor, game)
            try:
                view = self.games.read_view(connection, access)
            except GameError as error:
                if error.code != "game_not_started":
                    raise
                view = None
            events = self.games.read_events(
                connection,
                access,
                after_sequence,
                limit,
                through_state_version=game.state_version,
            )
            content = {
                "game_id": game_id,
                "game_type": game.game_type,
                "ruleset_id": game.ruleset_id,
                "ruleset_version": game.ruleset_version,
                "status": game.status,
                "state_version": game.state_version,
                "participation_id": access.participation_id,
                "seat_id": access.seat_id,
                "view": None if view is None else view.model_dump(mode="json"),
                "events": events.model_dump(mode="json"),
            }
            observation = ActivityObservation(
                observation_id=(
                    f"game:{game_id}:{access.participation_id}:"
                    f"{game.state_version}:{after_sequence}:{events.next_sequence}"
                ),
                community_id=community_id,
                activity_id=game_id,
                observer=actor,
                occurred_at_utc=game.updated_at_utc,
                state_version=game.state_version,
                audience=(actor,),
                content=json.dumps(content, ensure_ascii=False),
            )
            return CharacterGameObservation(context, view, events, observation)

    def events(
        self,
        community_id: str,
        character_id: str,
        game_id: str,
        participation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 50,
        through_state_version: int | None = None,
    ) -> GameEventBatch:
        with self.database.read() as connection:
            context = self.participation.participant_context(
                connection,
                community_id,
                ActorRef("character", character_id),
                game_id,
                participation_id,
                current=False,
            )
            return self.games.read_events(
                connection,
                context.access,
                after_sequence,
                limit,
                through_state_version=through_state_version,
            )
