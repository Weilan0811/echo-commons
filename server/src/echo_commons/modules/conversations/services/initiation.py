import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import GameConversationAccess
from echo_commons.modules.conversations.domain.conversation import (
    ConversationKind,
    ConversationStatus,
)
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.social.planner import TurnPlanner
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, ConversationArchived, IdempotencyConflict


class ConversationInitiation:
    def __init__(
        self,
        database: Database,
        communities: CommunityReader,
        conversations: ConversationRepository,
        instances: InstanceReader,
        planner: TurnPlanner,
        game_access: GameConversationAccess,
    ) -> None:
        self.database, self.communities, self.conversations = database, communities, conversations
        self.instances, self.planner, self.game_access = instances, planner, game_access

    def request(
        self,
        community_id: str,
        conversation_id: str,
        character_id: str,
        situation: str,
        *,
        request_id: str,
    ) -> str:
        with self.database.transaction() as connection:
            return self.request_in(
                connection,
                community_id,
                conversation_id,
                character_id,
                situation,
                request_id=request_id,
            )

    def request_in(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        conversation_id: str,
        character_id: str,
        situation: str,
        *,
        request_id: str,
    ) -> str:
        if not connection.in_transaction:
            raise RuntimeError("Initiation requests require a caller-owned transaction")
        if not situation.strip() or not request_id.strip():
            raise ValueError("Situation and request ID must be nonempty")
        existing = connection.execute(
            "SELECT i.*,t.task_id FROM conversation_initiations i "
            "JOIN social_turns s USING(initiation_id) "
            "JOIN conversation_tasks t ON t.social_turn_id=s.social_turn_id "
            "WHERE i.community_id=? AND i.request_id=?",
            (community_id, request_id),
        ).fetchone()
        if existing is not None:
            if (existing["conversation_id"], existing["character_id"], existing["situation"]) != (
                conversation_id,
                character_id,
                situation,
            ):
                raise IdempotencyConflict("Initiation request ID records a different request")
            return existing["task_id"]
        now = datetime.now(UTC)
        conversation = self.conversations.get(connection, community_id, conversation_id)
        if conversation.status is not ConversationStatus.ACTIVE:
            raise ConversationArchived("Archived conversation does not accept initiations")
        actor = ActorRef("character", character_id)
        member = self.conversations.current(connection, conversation_id, actor)
        self.communities.require_member(connection, community_id, actor)
        instance = self.instances.get(connection, community_id, character_id)
        instance.require_ready()
        if instance.availability_status is not AvailabilityStatus.AVAILABLE:
            raise ConflictError("Character is unavailable for conversation")
        if conversation.kind is ConversationKind.GAME and not self.game_access.can_send(
            connection, community_id, conversation_id, actor
        ):
            raise ConflictError("Game does not accept new conversation messages")
        identity = str(uuid4())
        audience = tuple(
            item.membership_id for item in self.conversations.members(connection, conversation_id)
        )
        connection.execute(
            "INSERT INTO conversation_initiations "
            "(initiation_id,community_id,conversation_id,character_id,request_id,situation,"
            "audience_json,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
            (
                identity,
                community_id,
                conversation_id,
                character_id,
                request_id,
                situation,
                json.dumps(audience),
                utc_text(now),
            ),
        )
        return self.planner.initiate(
            connection, conversation, member, identity, situation, audience, now
        )
