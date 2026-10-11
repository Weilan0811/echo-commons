from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationLifecycle
from echo_commons.modules.conversations.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationStatus,
    Membership,
    validate_members,
)
from echo_commons.modules.conversations.member_operations import (
    MembershipOperation,
    MembershipResult,
)
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.member_operations import (
    MembershipOperationRepository,
)
from echo_commons.modules.conversations.services.events import conversation_changed
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import (
    ConflictError,
    ConversationArchived,
    MembershipIntervalConflict,
    MembershipVersionConflict,
    NotFoundError,
)


class ConversationService:
    def __init__(
        self,
        database: Database,
        communities: CommunityReader,
        conversations: ConversationRepository,
        lifecycle: ConversationLifecycle,
    ) -> None:
        self.database, self.communities, self.conversations = database, communities, conversations
        self.lifecycle = lifecycle

    def community_id(self, conversation_id: str) -> str:
        with self.database.read() as connection:
            return self.conversations.community_id(connection, conversation_id)

    def list(self, community_id: str) -> tuple[Conversation, ...]:
        with self.database.read() as connection:
            self.communities.get(connection, community_id)
            return self.conversations.list(connection, community_id)

    def create(
        self,
        community_id: str,
        kind: ConversationKind,
        actors: tuple[ActorRef, ...],
        *,
        conversation_id: str | None = None,
        player_id: str | None = None,
    ) -> Conversation:
        kind = ConversationKind(kind)
        validate_members(kind, actors)
        conversation_id = str(uuid4()) if conversation_id is None else conversation_id
        if not conversation_id.strip():
            raise ValueError("Conversation ID must be nonempty")
        with self.database.transaction() as connection:
            now = utc_text(datetime.now(UTC))
            if player_id is not None:
                sender = ActorRef("player", player_id)
                self.communities.require_member(connection, community_id, sender)
                if sender not in actors:
                    raise ValueError("Conversation must include its initiating player")
            self.communities.get(connection, community_id)
            for actor in actors:
                self.communities.require_member(connection, community_id, actor)
                if actor.kind.value == "character":
                    InstanceRepository().get(
                        connection, community_id, actor.actor_id
                    ).require_ready()
            existing = connection.execute(
                "SELECT community_id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if existing:
                if existing["community_id"] != community_id:
                    raise ConflictError("Conversation ID belongs to another community")
                conversation = self.conversations.get(connection, community_id, conversation_id)
                current = {
                    member.actor
                    for member in self.conversations.members(connection, conversation_id)
                }
                if conversation.kind != kind or current != set(actors):
                    raise ConflictError("Conversation ID already has different content")
                return conversation
            connection.execute(
                "INSERT INTO conversations (conversation_id, community_id, kind, "
                "membership_version, created_at_utc, updated_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, community_id, kind.value, len(actors), now, now),
            )
            for actor in actors:
                connection.execute(
                    "INSERT INTO conversation_memberships (membership_id, community_id, "
                    "conversation_id, actor_kind, actor_id, joined_after_sequence, "
                    "joined_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        community_id,
                        conversation_id,
                        actor.kind.value,
                        actor.actor_id,
                        0,
                        now,
                    ),
                )
            conversation_changed(connection, conversation_id)
            return self.conversations.get(connection, community_id, conversation_id)

    def join(self, community_id: str, conversation_id: str, actor: ActorRef) -> Membership:
        with self.database.transaction() as connection:
            return self._join(connection, community_id, conversation_id, actor)

    def _join(
        self, connection, community_id: str, conversation_id: str, actor: ActorRef
    ) -> Membership:
        now = utc_text(datetime.now(UTC))
        conversation = self.conversations.get(connection, community_id, conversation_id)
        if conversation.status is not ConversationStatus.ACTIVE:
            raise ConversationArchived("Archived conversation cannot accept members")
        self.communities.require_member(connection, community_id, actor)
        if actor.kind.value == "character":
            InstanceRepository().get(connection, community_id, actor.actor_id).require_ready()
        current = self.conversations.members(connection, conversation_id)
        for member in current:
            if member.actor == actor:
                return member
        if conversation.kind is ConversationKind.DIRECT:
            original = connection.execute(
                "SELECT actor_kind,actor_id FROM conversation_memberships "
                "WHERE conversation_id=? ORDER BY joined_at_utc,membership_id LIMIT 2",
                (conversation_id,),
            ).fetchall()
            if actor not in {ActorRef(row[0], row[1]) for row in original}:
                raise ConflictError("Direct conversation participants are fixed")
        else:
            validate_members(
                conversation.kind, tuple(member.actor for member in current) + (actor,)
            )
        connection.execute(
            "INSERT INTO conversation_memberships (membership_id, community_id, "
            "conversation_id, actor_kind, actor_id, joined_after_sequence, "
            "joined_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                community_id,
                conversation_id,
                actor.kind.value,
                actor.actor_id,
                conversation.next_sequence - 1,
                now,
            ),
        )
        connection.execute(
            "UPDATE conversations SET membership_version = membership_version + 1, "
            "updated_at_utc = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )
        connection.execute(
            "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
            "updated_at_utc = ? WHERE conversation_id = ? AND status = 'collecting'",
            (now, now, conversation_id),
        )
        conversation_changed(connection, conversation_id)
        return self.conversations.current(connection, conversation_id, actor)

    def leave(self, community_id: str, conversation_id: str, actor: ActorRef) -> Membership:
        with self.database.transaction() as connection:
            return self._leave(connection, community_id, conversation_id, actor)

    def _leave(
        self, connection, community_id: str, conversation_id: str, actor: ActorRef
    ) -> Membership:
        now = utc_text(datetime.now(UTC))
        conversation = self.conversations.get(connection, community_id, conversation_id)
        member = self.conversations.current(connection, conversation_id, actor)
        connection.execute(
            "UPDATE conversation_memberships SET left_at_sequence = ?, left_at_utc = "
            "? WHERE membership_id = ?",
            (conversation.next_sequence - 1, now, member.membership_id),
        )
        connection.execute(
            "UPDATE conversations SET membership_version = membership_version + 1, "
            "updated_at_utc = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )
        # 批次在成员变动时结束，后续输入采用新的实际受众。
        connection.execute(
            "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
            "updated_at_utc = ? WHERE conversation_id = ? AND status = 'collecting'",
            (now, now, conversation_id),
        )
        self.lifecycle.member_left(connection, member.membership_id, datetime.fromisoformat(now))
        conversation_changed(
            connection,
            conversation_id,
            leaving_player=actor.actor_id if actor.kind.value == "player" else None,
        )
        row = connection.execute(
            "SELECT * FROM conversation_memberships WHERE membership_id = ?",
            (member.membership_id,),
        ).fetchone()
        return self.conversations.membership(row)

    def archive(self, community_id: str, conversation_id: str) -> Conversation:
        with self.database.transaction() as connection:
            conversation = self.conversations.get(connection, community_id, conversation_id)
            if conversation.status is ConversationStatus.ARCHIVED:
                return conversation
            now = datetime.now(UTC)
            connection.execute(
                "UPDATE conversations SET status = 'archived', updated_at_utc = ? "
                "WHERE conversation_id = ?",
                (utc_text(now), conversation_id),
            )
            connection.execute(
                "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
                "updated_at_utc = ? WHERE conversation_id = ? AND status = 'collecting'",
                (utc_text(now), utc_text(now), conversation_id),
            )
            self.lifecycle.archived(connection, conversation_id, now)
            conversation_changed(connection, conversation_id)
            return self.conversations.get(connection, community_id, conversation_id)

    def apply_membership(self, request: MembershipOperation, operation_id: str) -> MembershipResult:
        if not operation_id.strip():
            raise ValueError("Client operation ID must be nonempty")
        scope = (
            f"player:{request.player_id}"
            if request.player_id is not None
            else f"management:{request.community_id}"
        )
        records = MembershipOperationRepository()
        with self.database.transaction() as connection:
            conversation = self.conversations.get(
                connection, request.community_id, request.conversation_id
            )
            previous = records.previous(connection, scope, operation_id, request)
            if previous is not None:
                return previous
            if request.player_id is not None:
                if request.actor != ActorRef("player", request.player_id):
                    raise NotFoundError("Player can only modify their own membership")
                self.communities.require_member(connection, request.community_id, request.actor)
                if not any(
                    member.actor == request.actor
                    for member in self.conversations.members(
                        connection, request.conversation_id, current_only=False
                    )
                ):
                    raise NotFoundError("Player has not participated in this conversation")
                if request.action == "leave":
                    current = [
                        member
                        for member in self.conversations.members(
                            connection, request.conversation_id
                        )
                        if member.actor == request.actor
                    ]
                    if not current or current[0].membership_id != request.expected_membership_id:
                        raise MembershipIntervalConflict("Current membership interval has changed")
            elif request.expected_membership_version != conversation.membership_version:
                raise MembershipVersionConflict("Conversation membership version has changed")
            member = (self._join if request.action == "join" else self._leave)(
                connection, request.community_id, request.conversation_id, request.actor
            )
            version = self.conversations.get(
                connection, request.community_id, request.conversation_id
            ).membership_version
            result = MembershipResult(
                membership=member,
                membership_version=version,
                self_membership_status="current" if member.left_at_utc is None else "past",
            )
            records.add(
                connection, scope, operation_id, request, result, utc_text(datetime.now(UTC))
            )
            return result
