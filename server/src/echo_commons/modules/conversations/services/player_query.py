import base64
import binascii
from dataclasses import asdict
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.conversation import (
    ConversationKind,
    ConversationStatus,
)
from echo_commons.modules.conversations.domain.message import MessageVisibility
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.policy import visible_message_sql
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import InvalidCursor, NotFoundError
from echo_commons.shared.management import read_page
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


class HistoryCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    player_id: str
    conversation_id: str
    upper: int = Field(ge=0)
    before: int = Field(ge=1)


class PlayerConversationQuery:
    def __init__(self, messages, identity):
        self.query = messages
        self.database = messages.database
        self.conversations = messages.conversations
        self.messages = messages.messages
        self.perspective = messages.perspective
        self.identity = identity
        self.communities = CommunityRepository()

    def scope(self, connection, conversation_id, player_id):
        community_id = self.conversations.community_id(connection, conversation_id)
        conversation = self.conversations.get(connection, community_id, conversation_id)
        scope = ObservationScope(
            community_id,
            conversation_id,
            ActorRef("player", player_id),
            conversation.next_sequence - 1,
        )
        self.perspective.memberships(connection, scope)
        return conversation, scope

    def preview(self, connection, message):
        return {
            "message_id": message.message_id,
            "sequence": message.sequence,
            "sender_display": self.identity.display(
                connection, message.community_id, message.sender
            ),
            "text_preview": message.text[:160],
            "visibility": message.visibility,
            "created_at_utc": message.created_at_utc,
        }

    def view(self, connection, scope, message):
        data = {
            key: getattr(message, key)
            for key in (
                "message_id",
                "conversation_id",
                "sequence",
                "sender",
                "text",
                "visibility",
                "mentions",
                "reply_to_message_id",
                "source_turn_id",
                "created_at_utc",
            )
        }
        data["sender_display"] = self.identity.display(
            connection, scope.community_id, message.sender
        )
        data["recipients"] = []
        if message.visibility is MessageVisibility.RECIPIENTS:
            data["recipients"] = [
                self.identity.display(connection, scope.community_id, actor)
                for actor in sorted(
                    self.messages.audience_actors(connection, message),
                    key=lambda actor: (actor.kind, actor.actor_id),
                )
            ]
        data["reply_preview"] = None
        if message.reply_to_message_id:
            target = self.messages.get(
                connection, scope.conversation_id, message.reply_to_message_id
            )
            if self.perspective.visible(connection, scope, target):
                data["reply_preview"] = self.preview(connection, target)
        return data

    def read(self, conversation_id, player_id, *, cursor=None, limit=50):
        # 增量扫描仍沿用原协议，展示投影在同一读取事务完成。
        with self.database.read() as connection:
            conversation, scope = self.scope(connection, conversation_id, player_id)
            page = self.query.read_in(connection, conversation, scope, cursor=cursor, limit=limit)
            return {
                "messages": [self.view(connection, scope, message) for message in page.messages],
                "cursor": page.cursor,
                "has_more": page.has_more,
            }

    def message(self, conversation_id, player_id, message_id):
        with self.database.read() as connection:
            _, scope = self.scope(connection, conversation_id, player_id)
            message = self.messages.get(connection, conversation_id, message_id)
            if not self.perspective.visible(connection, scope, message):
                raise NotFoundError("Message is not visible to this player")
            return self.view(connection, scope, message)

    def history(self, conversation_id, player_id, *, older_cursor=None, limit=50):
        if not 1 <= limit <= 200:
            raise ValueError("History limit must be between 1 and 200")
        with self.database.read() as connection:
            _, scope = self.scope(connection, conversation_id, player_id)
            upper, before = scope.upper_sequence, scope.upper_sequence + 1
            if older_cursor is not None:
                try:
                    decoded = base64.b64decode(older_cursor, altchars=b"-_", validate=True)
                    cursor = HistoryCursor.model_validate_json(decoded)
                except (ValueError, binascii.Error, ValidationError) as error:
                    raise InvalidCursor("Invalid history cursor") from error
                if (cursor.player_id, cursor.conversation_id) != (player_id, conversation_id):
                    raise InvalidCursor("History cursor belongs to a different query")
                upper, before = cursor.upper, cursor.before
            rows = connection.execute(
                "SELECT m.* FROM messages m WHERE m.conversation_id=? AND m.sequence<=? "
                "AND m.sequence<? AND "
                + visible_message_sql()
                + " ORDER BY m.sequence DESC LIMIT ?",
                (conversation_id, upper, before, player_id, limit + 1),
            ).fetchall()
            has_older = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if has_older:
                value = HistoryCursor(
                    player_id=player_id,
                    conversation_id=conversation_id,
                    upper=upper,
                    before=rows[-1]["sequence"],
                )
                next_cursor = base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()
            return {
                "messages": [
                    self.view(connection, scope, self.messages.from_row(connection, row))
                    for row in reversed(rows)
                ],
                "older_cursor": next_cursor,
                "has_older": has_older,
                "poll_cursor": self.query.encode(scope, upper) if older_cursor is None else None,
            }

    def read_state(self, connection, scope):
        position = connection.execute(
            "SELECT last_read_sequence FROM conversation_read_positions WHERE player_id=? "
            "AND conversation_id=?",
            (scope.actor.actor_id, scope.conversation_id),
        ).fetchone()
        position = position[0] if position else 0
        count = connection.execute(
            "SELECT COUNT(*) FROM messages m WHERE m.conversation_id=? AND m.sequence>? "
            "AND NOT (m.sender_kind='player' AND m.sender_id=?) AND " + visible_message_sql(),
            (scope.conversation_id, position, scope.actor.actor_id, scope.actor.actor_id),
        ).fetchone()[0]
        return {
            "conversation_id": scope.conversation_id,
            "last_read_sequence": position,
            "unread_count": count,
        }

    def mark_read(self, conversation_id, player_id, message_id):
        with self.database.transaction() as connection:
            _, scope = self.scope(connection, conversation_id, player_id)
            previous = self.read_state(connection, scope)["last_read_sequence"]
            message = self.messages.get(connection, conversation_id, message_id)
            if not self.perspective.visible(connection, scope, message):
                raise NotFoundError("Read marker message is not visible to this player")
            connection.execute(
                "INSERT INTO conversation_read_positions VALUES (?,?,?,?) "
                "ON CONFLICT(player_id,conversation_id) DO UPDATE SET "
                "last_read_sequence=MAX(last_read_sequence,excluded.last_read_sequence), "
                "updated_at_utc=excluded.updated_at_utc",
                (player_id, conversation_id, message.sequence, utc_text(datetime.now(UTC))),
            )
            if message.sequence > previous:
                for kind in (EventKind.READ, EventKind.SUMMARY):
                    record_event(
                        connection,
                        EventReference(
                            kind,
                            scope.community_id,
                            conversation_id,
                            EventSource.READ,
                            player_id,
                        ),
                    )
            return self.read_state(connection, scope)

    def summary(self, connection, conversation, scope):
        members = self.conversations.members(
            connection, conversation.conversation_id, current_only=False
        )
        current = next(
            (
                member
                for member in members
                if member.actor == scope.actor and member.left_at_utc is None
            ),
            None,
        )
        last = connection.execute(
            "SELECT m.* FROM messages m WHERE m.conversation_id=? AND "
            + visible_message_sql()
            + " ORDER BY m.sequence DESC LIMIT 1",
            (scope.conversation_id, scope.actor.actor_id),
        ).fetchone()
        last = self.messages.from_row(connection, last) if last else None
        peer = None
        if conversation.kind is ConversationKind.DIRECT:
            peer = next(
                (member.actor for member in members if member.actor.kind.value == "character"), None
            )
        direct_peer = self.identity.display(connection, scope.community_id, peer) if peer else None
        if direct_peer is not None:
            display_name = direct_peer.display_name
        elif current is None:
            # 离开者不能读取当前成员名单，标题也不透露后来加入的成员。
            display_name = "已离开的群聊"
        else:
            peers = [
                member.actor
                for member in members
                if member.left_at_utc is None and member.actor != scope.actor
            ]
            names = [
                self.identity.display(connection, scope.community_id, actor).display_name
                for actor in peers[:3]
            ]
            display_name = "、".join(names) if names else "只有你"
            if len(peers) > 3:
                display_name += f" 等 {len(peers)} 人"
        data = asdict(conversation)
        data.pop("next_sequence")
        data.pop("updated_at_utc")
        data.update(self.read_state(connection, scope))
        data.update(
            display_name=display_name,
            creator_display=self.identity.display(
                connection, scope.community_id, ActorRef("player", conversation.creator_player_id)
            )
            if conversation.creator_player_id
            else None,
            hidden=bool(
                (
                    connection.execute(
                        "SELECT hidden FROM conversation_list_preferences "
                        "WHERE player_id=? AND conversation_id=?",
                        (scope.actor.actor_id, scope.conversation_id),
                    ).fetchone()
                    or [False]
                )[0]
            ),
            can_archive=conversation.kind is ConversationKind.GROUP
            and conversation.status is ConversationStatus.ACTIVE
            and conversation.creator_player_id == scope.actor.actor_id,
            can_join=current is None and conversation.status is ConversationStatus.ACTIVE,
            can_leave=current is not None and conversation.status is ConversationStatus.ACTIVE,
            self_membership_status="current" if current else "past",
            self_membership_id=current.membership_id if current else None,
            can_send=current is not None and conversation.status is ConversationStatus.ACTIVE,
            direct_peer=direct_peer,
            last_message=self.preview(connection, last) if last else None,
            last_visible_message_at_utc=last.created_at_utc if last else None,
        )
        return data

    def conversation(self, conversation_id, player_id):
        with self.database.read() as connection:
            conversation, scope = self.scope(connection, conversation_id, player_id)
            return self.summary(connection, conversation, scope)

    def conversations_for(
        self,
        player_id,
        options,
        *,
        community_id=None,
        membership="current",
        status="active",
        view=None,
    ):
        with self.database.read() as connection:
            self.communities.player(connection, player_id)
            if community_id is not None:
                self.communities.require_member(
                    connection, community_id, ActorRef("player", player_id)
                )
            condition = ""
            view = view or ("active" if membership == "current" and status == "active" else "all")
            current_sql = (
                "EXISTS (SELECT 1 FROM conversation_memberships cm WHERE "
                "cm.conversation_id=c.conversation_id AND cm.actor_kind='player' "
                "AND cm.actor_id=p.player_id AND cm.left_at_utc IS NULL)"
            )
            hidden_sql = (
                "COALESCE((SELECT hidden FROM conversation_list_preferences lp "
                "WHERE lp.player_id=p.player_id AND lp.conversation_id=c.conversation_id),0)"
            )
            if view == "active":
                condition += f" AND c.status='active' AND {current_sql} AND {hidden_sql}=0"
            elif view == "history":
                condition += f" AND {hidden_sql}=0 AND (c.status='archived' OR NOT {current_sql})"
                membership, status = "all", "all"
            elif view == "hidden":
                condition += f" AND {hidden_sql}=1"
                membership, status = "all", "all"
            elif view == "archived":
                condition += f" AND c.status='archived' AND {hidden_sql}=0"
                membership, status = "all", "all"
            if membership != "all":
                condition += (
                    " AND "
                    + ("" if membership == "current" else "NOT ")
                    + (
                        "EXISTS (SELECT 1 FROM conversation_memberships cm WHERE "
                        "cm.conversation_id=c.conversation_id AND cm.actor_kind='player' "
                        "AND cm.actor_id=p.player_id AND cm.left_at_utc IS NULL)"
                    )
                )
            if status != "all":
                condition += " AND c.status=?"
            if community_id is not None:
                condition += " AND c.community_id=?"
            parameters = (
                (player_id,)
                + (() if status == "all" else (status,))
                + (() if community_id is None else (community_id,))
            )
            sql = (
                "SELECT c.*, COALESCE((SELECT MAX(m.created_at_utc) FROM messages m "
                "WHERE m.conversation_id=c.conversation_id AND "
                + visible_message_sql(player_expression="p.player_id")
                + "),c.created_at_utc) AS activity_order FROM conversations c JOIN players p "
                "ON p.player_id=? WHERE EXISTS (SELECT 1 FROM conversation_memberships h "
                "WHERE h.conversation_id=c.conversation_id AND h.actor_kind='player' "
                "AND h.actor_id=p.player_id)" + condition
            )
            page = read_page(
                connection,
                sql,
                parameters,
                scope={
                    "query": "player_conversations",
                    "player_id": player_id,
                    "community_id": community_id,
                    "membership": membership,
                    "status": status,
                    "view": view,
                },
                order=("activity_order", "conversation_id"),
                options=options,
                descending=True,
            )
            page["items"] = [
                self.summary(connection, *self.scope(connection, row["conversation_id"], player_id))
                for row in page["items"]
            ]
            return page

    def members(self, conversation_id, player_id, options):
        with self.database.read() as connection:
            _, scope = self.scope(connection, conversation_id, player_id)
            self.conversations.current(connection, conversation_id, scope.actor)
            page = read_page(
                connection,
                "SELECT * FROM conversation_memberships WHERE conversation_id=? "
                "AND left_at_utc IS NULL",
                (conversation_id,),
                scope={
                    "query": "player_members",
                    "player_id": player_id,
                    "conversation_id": conversation_id,
                },
                order=("joined_at_utc", "membership_id"),
                options=options,
            )
            page["items"] = [
                self.identity.display(
                    connection, scope.community_id, ActorRef(row["actor_kind"], row["actor_id"])
                )
                for row in page["items"]
            ]
            return page
