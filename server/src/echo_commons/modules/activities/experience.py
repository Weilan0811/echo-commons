import json
from dataclasses import dataclass
from datetime import datetime

from echo_games.public import Participation

from echo_commons.modules.perspective.contracts import ConversationBoundary
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True)
class GameExperience:
    participation: Participation
    community_id: str
    character_id: str
    game_type: str
    boundary: ConversationBoundary
    closed_at: datetime | None
    state_version: int
    events: tuple
    through_sequence: int
    status: str
    result: object
    has_more: bool
    updated_at: datetime


class ActivityExperiences:
    def __init__(self, observations, conversations, names):
        self.observations, self.conversations, self.names = observations, conversations, names

    def read(
        self, connection, community_id, character_id, participation_id, now, *, after=0, limit=200
    ):
        actor = ActorRef("character", character_id)
        participation = next(
            p
            for p in self.observations.participation.participations(connection, community_id, actor)
            if p.participation_id == participation_id
        )
        context = self.observations.participation.participant_context(
            connection, community_id, actor, participation.game_id, participation_id, current=False
        )
        conversation = self.conversations.get(connection, community_id, context.conversation_id)
        members = self.conversations.members(
            connection, context.conversation_id, current_only=False
        )
        member = next(
            m
            for m in members
            if m.actor == actor
            and m.joined_at_utc >= participation.joined_at_utc
            and (participation.left_at_utc is None or m.joined_at_utc <= participation.left_at_utc)
        )
        endings = [
            t
            for t in (
                participation.left_at_utc,
                member.left_at_utc,
                conversation.updated_at_utc if conversation.status == "archived" else None,
                context.game.updated_at_utc if context.game.status == "cancelled" else None,
            )
            if t is not None and t <= now
        ]
        closed = min(endings, default=None)
        version = participation.left_state_version or context.game.state_version
        batch = self.observations.games.read_events(
            connection, context.access, after, limit, through_state_version=version
        )
        cutoff = min(now, closed) if closed else now
        events = tuple(e for e in batch.items if e.occurred_at_utc <= cutoff)
        future = [e.sequence for e in batch.items if e.occurred_at_utc > cutoff]
        through = min(future) - 1 if future else batch.next_sequence
        boundary = ConversationBoundary(
            conversation_id=conversation.conversation_id,
            kind="game",
            name=f"{context.game.game_type} 对局",
            upper_sequence=min(
                conversation.next_sequence - 1,
                member.left_at_sequence
                if member.left_at_sequence is not None
                else conversation.next_sequence - 1,
            ),
            membership_ids=(member.membership_id,),
        )
        return GameExperience(
            participation,
            community_id,
            character_id,
            context.game.game_type,
            boundary,
            closed,
            version,
            events,
            through,
            "left" if participation.left_at_utc else context.game.status,
            context.game.result.model_dump(mode="json")
            if participation.left_at_utc is None
            and context.game.result is not None
            and context.game.updated_at_utc <= now
            else None,
            batch.has_more and not future,
            min(context.game.updated_at_utc, closed or now, now),
        )

    def content(self, connection, experience, event):
        participants = tuple(
            m.actor
            for m in self.conversations.members(
                connection, experience.boundary.conversation_id, current_only=False
            )
            if m.joined_at_utc <= event.occurred_at_utc
            and (m.left_at_utc is None or m.left_at_utc >= event.occurred_at_utc)
        )
        names = {
            f"{a.kind.value}:{a.actor_id}": self.names.actor_name(
                connection, experience.community_id, a
            )
            for a in participants
        }
        text = json.dumps(
            {
                "game_type": experience.game_type,
                "event": event.type,
                "data": event.data.model_dump(mode="json"),
                "participants": names,
            },
            ensure_ascii=False,
        )
        return text, participants
