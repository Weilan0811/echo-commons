from datetime import datetime

from pydantic import BaseModel, ConfigDict

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


class ObservedGameEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    version: str
    content: str
    occurred_at_utc: datetime
    conversation_id: str
    participation_id: str
    game_id: str
    actors: tuple[ActorRef, ...]


class ActivityPerspective:
    def __init__(self, experiences):
        self.experiences = experiences

    def session_context(self, connection, community_id, character_id, participation_id, now):
        return self.experiences.read(
            connection, community_id, character_id, participation_id, now, limit=1
        ).session_context

    def event(self, connection, community_id, character_id, event_id, now):
        row = connection.execute(
            "SELECT r.*,e.game_id,e.conversation_id FROM memory_activity_event_refs r "
            "JOIN memory_activity_episodes e USING(participation_id) "
            "WHERE r.community_id=? AND r.character_id=? AND r.event_id=?",
            (community_id, character_id, event_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Game event does not belong to this character experience")
        observed = self.experiences.read(
            connection,
            community_id,
            character_id,
            row["participation_id"],
            now,
            after=row["event_sequence"] - 1,
            limit=1,
        )
        event = next((e for e in observed.events if e.event_id == event_id), None)
        if event is None or str(event.state_version) != row["source_version"]:
            raise NotFoundError("Game event is outside the original participation")
        content, actors = self.experiences.content(connection, observed, event)
        return ObservedGameEvent(
            source_id=event.event_id,
            version=str(event.state_version),
            content=content,
            occurred_at_utc=event.occurred_at_utc,
            conversation_id=row["conversation_id"],
            participation_id=row["participation_id"],
            game_id=row["game_id"],
            actors=actors,
        )

    def thought_visible(self, connection, community_id, character_id, thought, now):
        row = connection.execute(
            "SELECT i.participation_id,r.created_at_utc FROM activity_results r "
            "JOIN activity_tasks t USING(task_id) JOIN activity_inputs i USING(input_id) "
            "WHERE r.result_id=? AND t.community_id=? AND t.character_id=?",
            (thought["activity_result_id"], community_id, character_id),
        ).fetchone()
        if row is None:
            return False
        experience = self.experiences.read(
            connection, community_id, character_id, row["participation_id"], now, limit=1
        )
        created = utc_datetime(thought["created_at_utc"])
        return (
            created <= now
            and (experience.closed_at is None or created <= experience.closed_at)
            and created >= experience.participation.joined_at_utc
        )
