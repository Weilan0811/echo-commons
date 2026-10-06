from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import jieba

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.materials import MemoryMaterials
from echo_commons.modules.memory.services.tokenization import tokenized_text
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorKind, ActorRef


class MemoryIndexing:
    def __init__(
        self,
        instances: InstanceReader,
        conversations: ConversationRepository,
        perspective: PerspectiveReader,
        search: SearchRepository,
        entries: MemoryEntryRepository,
    ) -> None:
        self.instances, self.conversations, self.perspective, self.search = (
            instances,
            conversations,
            perspective,
            search,
        )
        jieba.initialize()
        self.entries = entries

    def message(self, connection: sqlite3.Connection, message: Message) -> None:
        for member in self.conversations.members(
            connection, message.conversation_id, current_only=False
        ):
            if member.actor.kind is not ActorKind.CHARACTER:
                continue
            scope = ObservationScope(
                message.community_id,
                message.conversation_id,
                member.actor,
                message.sequence,
                member.membership_id,
            )
            if self.perspective.visible(connection, scope, message):
                self.search.replace(
                    connection,
                    message.community_id,
                    member.actor.actor_id,
                    message.conversation_id,
                    "message",
                    message.message_id,
                    "1",
                    message.text,
                    tokenized_text(message.text),
                    message.created_at_utc,
                    message.created_at_utc,
                )

    def memories(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, now: datetime
    ) -> None:
        self.instances.get(connection, community_id, character_id)
        for row in self.entries.active_rows(
            connection,
            community_id,
            character_id,
            valid_at=now,
            recorded_before=now,
        ):
            self.search.replace(
                connection,
                community_id,
                character_id,
                None,
                "memory_entry",
                row["memory_id"],
                row["content_version"],
                row["content"],
                tokenized_text(row["content"]),
                utc_datetime(row["occurred_at_utc"]) if row["occurred_at_utc"] else None,
                now,
            )

    def rebuild(self, connection: sqlite3.Connection, community_id: str, character_id: str) -> None:
        self.instances.get(connection, community_id, character_id)
        now = datetime.now(UTC)
        self.search.clear(connection, community_id, character_id)
        self.memories(connection, community_id, character_id, now)
        materials = MemoryMaterials(self.search)
        materials.authors(connection, community_id, character_id, now)
        materials.summaries(connection, community_id, character_id, now)
        for conversation in self.conversations.for_actor(
            connection, community_id, ActorRef("character", character_id)
        ):
            scope = ObservationScope(
                community_id,
                conversation.conversation_id,
                ActorRef("character", character_id),
                conversation.next_sequence - 1,
            )
            for message in self.perspective.messages(connection, scope):
                self.search.replace(
                    connection,
                    community_id,
                    character_id,
                    conversation.conversation_id,
                    "message",
                    message.message_id,
                    "1",
                    message.text,
                    tokenized_text(message.text),
                    message.created_at_utc,
                    now,
                )
