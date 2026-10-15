import json

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.perspective.policy import can_observe
from echo_commons.shared.actors import ActorRef


class RelationshipEvidenceReader:
    def read(self, connection, community_id, character_id, target_kind, target_id, now, max_chars):
        evidence, size = [], 0
        for row in connection.execute(
            "SELECT * FROM relation_evidence WHERE community_id=? AND observer_character_id=? "
            "AND target_kind=? AND target_id=? AND recorded_at_utc<=? "
            "ORDER BY recorded_at_utc DESC,evidence_id LIMIT 8",
            (community_id, character_id, target_kind, target_id, utc_text(now)),
        ):
            content = self.content(connection, community_id, character_id, row, now)
            item = dict(
                evidence_id=row["evidence_id"],
                evidence_kind=row["evidence_kind"],
                source_kind=row["source_kind"],
                source_ref=row["source_ref"],
                occurred_at_utc=row["occurred_at_utc"],
                content=content,
                content_status="readable" if content else "unavailable",
                target_messages=self.target_messages(
                    connection,
                    community_id,
                    character_id,
                    target_kind,
                    target_id,
                    row,
                    now,
                ),
            )
            length = len(json.dumps(item, ensure_ascii=False))
            if size + length > max_chars:
                continue
            evidence.append(item)
            size += length
        return evidence

    def target_messages(self, connection, community, character, kind, identity, evidence, now):
        rows = connection.execute(
            "SELECT m.* FROM relation_evidence_sources s JOIN messages m ON "
            "m.message_id=s.source_id "
            "WHERE s.evidence_id=? AND s.source_kind='message' AND m.community_id=? "
            "AND m.sender_kind=? AND m.sender_id=? AND m.created_at_utc<=? "
            "ORDER BY m.created_at_utc,m.message_id LIMIT 8",
            (evidence["evidence_id"], community, kind, identity, utc_text(now)),
        )
        return [
            dict(
                message_id=row["message_id"],
                sender_kind=row["sender_kind"],
                sender_id=row["sender_id"],
                content=row["text"],
                conversation_id=row["conversation_id"],
            )
            for row in rows
            if self.visible(connection, character, row)
        ]

    def content(self, connection, community_id, character_id, evidence, now):
        content = []
        for source in connection.execute(
            "SELECT * FROM relation_evidence_sources WHERE evidence_id=? ORDER BY "
            "source_kind,source_id",
            (evidence["evidence_id"],),
        ):
            if source["source_kind"] == "message":
                row = connection.execute(
                    "SELECT * FROM messages WHERE community_id=? AND message_id=? AND "
                    "created_at_utc<=?",
                    (community_id, source["source_id"], utc_text(now)),
                ).fetchone()
                if (
                    row is None
                    or source["source_version"] != "1"
                    or not self.visible(connection, character_id, row)
                ):
                    return ""
                content.append(
                    f"场景：{row['conversation_id']}\n发送者：{row['sender_kind']}:{row['sender_id']}\n{row['text']}"
                )
            else:
                row = connection.execute(
                    "SELECT * FROM thoughts WHERE community_id=? AND character_id=? AND "
                    "thought_id=? "
                    "AND created_at_utc<=?",
                    (community_id, character_id, source["source_id"], utc_text(now)),
                ).fetchone()
                if (
                    row is None
                    or not row["content"]
                    or row["content_version"] != source["source_version"]
                ):
                    return ""
                content.append(f"场景：{row['conversation_id']}\n自身私有念头：{row['content']}")
        return "\n\n".join(content)

    def visible(self, connection, character_id, row):
        message = MessageRepository().from_row(connection, row)
        return any(
            member.actor == ActorRef("character", character_id)
            and can_observe(message, member, message.sequence)
            for member in ConversationRepository().members(
                connection, message.conversation_id, current_only=False
            )
        )
