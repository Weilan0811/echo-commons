"""SQLite repositories for the Conversation Runtime model."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import aiosqlite

from echo_server.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationParticipant,
    ConversationStatus,
)
from echo_server.domain.errors import (
    DomainInvariantError,
    require_non_empty,
    require_sequence,
    require_utc,
)
from echo_server.domain.input_batch import QUIET_WINDOW_SECONDS, InputBatch
from echo_server.domain.messages import Message, MessageSender, SenderType
from echo_server.domain.result import AgentResult, AgentResultStatus
from echo_server.domain.state import CharacterState, WorldState
from echo_server.domain.task import ConversationTask
from echo_server.store.database import Database
from echo_server.store.memory_search_repositories import (
    MemorySearchUnavailableError,
    SearchIndexWriter,
)
from echo_server.store.repository_support import (
    as_json,
    get_connection,
    parse_time,
    require_write_connection,
    utc_text,
)


def _row_value(row: aiosqlite.Row, name: str, default: Any = None) -> Any:
    try:
        return row[name]
    except (IndexError, KeyError):
        return default


def _required_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise DomainInvariantError(f"{field_name} must contain a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must contain a UUID") from exc


def _optional_uuid(value: object, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _required_uuid(value, field_name)


def _required_time(value: object, field_name: str) -> datetime:
    parsed = parse_time(value if isinstance(value, str) else None)
    if parsed is None:
        raise DomainInvariantError(f"{field_name} must contain a timestamp")
    return parsed


def _optional_time(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _required_time(value, field_name)


def _check_rowcount(rowcount: int, entity: str) -> None:
    if rowcount != 1:
        raise RuntimeError(f"{entity} persistence precondition failed")


@dataclass(frozen=True, slots=True)
class MessageIdempotencyRecord:
    """Store-only projection used to resolve a client message replay."""

    message_id: UUID
    trace_id: UUID
    normalized_payload_hash: str | None


class RuntimeConversationRepository:
    """Persistence mapping for the new Conversation aggregate root."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> Conversation:
        return Conversation(
            conversation_id=row["conversation_id"],
            account_id=row["account_id"],
            kind=_row_value(row, "kind", "direct"),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            status=_row_value(row, "status", "active"),
            context_version=row["context_version"],
        )

    async def get(
        self,
        account_id: str,
        conversation_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> Conversation | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM conversations WHERE account_id = ? AND conversation_id = ?",
            (account_id, conversation_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def list_executable(
        self,
        account_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Conversation, ...]:
        """List active direct conversations eligible for isolated scheduling."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM conversations WHERE account_id = ? "
            "AND kind = 'direct' AND status = 'active' "
            "ORDER BY conversation_id",
            (account_id,),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def create(
        self,
        conversation: Conversation,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> Conversation:
        conn = require_write_connection(connection)
        await conn.execute(
            "INSERT INTO conversations(account_id, conversation_id, context_version, "
            "created_at_utc, updated_at_utc, kind, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                conversation.account_id,
                conversation.conversation_id,
                conversation.context_version,
                utc_text(conversation.created_at_utc),
                utc_text(conversation.updated_at_utc),
                conversation.kind.value,
                conversation.status.value,
            ),
        )
        stored = await self.get(
            conversation.account_id,
            conversation.conversation_id,
            connection=conn,
        )
        if stored is None:
            raise RuntimeError("conversation was not persisted")
        return stored

    async def ensure(
        self,
        *,
        account_id: str,
        conversation_id: str,
        now_utc: datetime,
        kind: ConversationKind = ConversationKind.DIRECT,
        status: ConversationStatus = ConversationStatus.ACTIVE,
        context_version: str = "0",
        connection: aiosqlite.Connection | None = None,
    ) -> Conversation:
        """Return the runtime conversation, creating its identity if needed."""

        conn = require_write_connection(connection)
        existing = await self.get(account_id, conversation_id, connection=conn)
        if existing is not None:
            return existing
        return await self.create(
            Conversation(
                conversation_id=conversation_id,
                account_id=account_id,
                kind=kind,
                status=status,
                context_version=context_version,
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
            ),
            connection=conn,
        )

    async def save(
        self,
        conversation: Conversation,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> Conversation:
        conn = require_write_connection(connection)
        cursor = await conn.execute(
            "UPDATE conversations SET kind = ?, status = ?, context_version = ?, "
            "updated_at_utc = ? WHERE account_id = ? AND conversation_id = ?",
            (
                conversation.kind.value,
                conversation.status.value,
                conversation.context_version,
                utc_text(conversation.updated_at_utc),
                conversation.account_id,
                conversation.conversation_id,
            ),
        )
        _check_rowcount(cursor.rowcount, "conversation")
        return conversation


class WorldStateRepository:
    """Read and compare-and-set persistence for the singleton world state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> WorldState:
        return WorldState(
            state_version=int(row["state_version"]),
            world_time_utc=_required_time(row["world_time_utc"], "world_time_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            status=row["status"],
            phase=row["phase"],
        )

    async def get(self, connection: aiosqlite.Connection | None = None) -> WorldState | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute("SELECT * FROM world_state WHERE singleton_id = 1")
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def save(
        self,
        state: WorldState,
        *,
        expected_version: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> WorldState:
        conn = require_write_connection(connection)
        values = (
            utc_text(state.world_time_utc),
            state.status.value,
            state.phase,
            utc_text(state.updated_at_utc),
        )
        if expected_version is None:
            cursor = await conn.execute(
                """INSERT INTO world_state(
                    singleton_id, state_version, world_time_utc, status, phase, updated_at_utc
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    state_version = excluded.state_version,
                    world_time_utc = excluded.world_time_utc,
                    status = excluded.status,
                    phase = excluded.phase,
                    updated_at_utc = excluded.updated_at_utc
                WHERE world_state.state_version < excluded.state_version""",
                (state.state_version, *values),
            )
        else:
            cursor = await conn.execute(
                "UPDATE world_state SET state_version = ?, world_time_utc = ?, status = ?, "
                "phase = ?, updated_at_utc = ? WHERE singleton_id = 1 AND state_version = ?",
                (
                    state.state_version,
                    *values,
                    expected_version,
                ),
            )
        _check_rowcount(cursor.rowcount, "world state")
        return state


class CharacterStateRepository:
    """Read and compare-and-set persistence for character availability."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> CharacterState:
        return CharacterState(
            character_id=row["character_id"],
            availability_status=row["availability_status"],
            state_version=int(row["state_version"]),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            reason_code=row["reason_code"],
            next_check_at_utc=_optional_time(row["next_check_at_utc"], "next_check_at_utc"),
        )

    async def get(
        self,
        character_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> CharacterState | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM character_states WHERE character_id = ?", (character_id,)
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def save(
        self,
        state: CharacterState,
        *,
        expected_version: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> CharacterState:
        conn = require_write_connection(connection)
        values = (
            state.availability_status.value,
            state.reason_code,
            utc_text(state.next_check_at_utc) if state.next_check_at_utc else None,
            state.state_version,
            utc_text(state.updated_at_utc),
        )
        if expected_version is None:
            cursor = await conn.execute(
                """INSERT INTO character_states(
                    character_id, availability_status, reason_code, next_check_at_utc,
                    state_version, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id) DO UPDATE SET
                    availability_status = excluded.availability_status,
                    reason_code = excluded.reason_code,
                    next_check_at_utc = excluded.next_check_at_utc,
                    state_version = excluded.state_version,
                    updated_at_utc = excluded.updated_at_utc
                WHERE character_states.state_version < excluded.state_version""",
                (state.character_id, *values),
            )
        else:
            cursor = await conn.execute(
                "UPDATE character_states SET availability_status = ?, reason_code = ?, "
                "next_check_at_utc = ?, state_version = ?, updated_at_utc = ? "
                "WHERE character_id = ? AND state_version = ?",
                (*values, state.character_id, expected_version),
            )
        _check_rowcount(cursor.rowcount, "character state")
        return state


class ConversationParticipantRepository:
    """Persistence for the only required conversation relationship table."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> ConversationParticipant:
        return ConversationParticipant(
            conversation_id=row["conversation_id"],
            character_id=row["character_id"],
            joined_at_utc=_required_time(row["joined_at_utc"], "joined_at_utc"),
            left_at_utc=_optional_time(row["left_at_utc"], "left_at_utc"),
        )

    async def get(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationParticipant | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM conversation_participants WHERE account_id = ? "
            "AND conversation_id = ? AND character_id = ?",
            (account_id, conversation_id, character_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def list_active(
        self,
        account_id: str,
        conversation_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[ConversationParticipant, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM conversation_participants WHERE account_id = ? "
            "AND conversation_id = ? AND left_at_utc IS NULL ORDER BY joined_at_utc, character_id",
            (account_id, conversation_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def save(
        self,
        participant: ConversationParticipant,
        *,
        account_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationParticipant:
        conn = require_write_connection(connection)
        account = require_non_empty(account_id, "account_id")
        await conn.execute(
            """INSERT INTO conversation_participants(
                account_id, conversation_id, character_id, joined_at_utc, left_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id, conversation_id, character_id) DO UPDATE SET
                joined_at_utc = excluded.joined_at_utc,
                left_at_utc = excluded.left_at_utc""",
            (
                account,
                participant.conversation_id,
                participant.character_id,
                utc_text(participant.joined_at_utc),
                utc_text(participant.left_at_utc) if participant.left_at_utc else None,
            ),
        )
        stored = await self.get(
            account,
            participant.conversation_id,
            participant.character_id,
            connection=conn,
        )
        if stored is None:
            raise RuntimeError("conversation participant was not persisted")
        return stored


class RuntimeMessageRepository:
    """Message persistence with strict new-runtime relationship links."""

    def __init__(
        self,
        database: Database,
        *,
        search_index: SearchIndexWriter | None = None,
    ) -> None:
        self.database = database
        self.search_index = search_index

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> Message:
        return Message(
            message_sequence=int(row["message_sequence"]),
            message_id=_required_uuid(row["message_id"], "message_id"),
            account_id=row["account_id"],
            conversation_id=row["conversation_id"],
            sender=MessageSender(type=row["sender_type"], id=row["sender_id"]),
            text=row["text"],
            images=tuple(json.loads(row["images_json"])),
            client_msg_id=_optional_uuid(row["client_msg_id"], "client_msg_id"),
            client_timestamp_utc=_optional_time(
                row["client_timestamp_utc"], "client_timestamp_utc"
            ),
            server_timestamp_utc=_required_time(
                row["server_timestamp_utc"], "server_timestamp_utc"
            ),
            reply_to_message_id=_optional_uuid(row["reply_to_message_id"], "reply_to_message_id"),
            trace_id=_required_uuid(row["trace_id"], "trace_id"),
            input_batch_id=_optional_uuid(_row_value(row, "input_batch_id"), "input_batch_id"),
            result_id=_optional_uuid(_row_value(row, "result_id"), "result_id"),
            bubble_index=_row_value(row, "bubble_index"),
        )

    async def _get_row(
        self,
        message_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM messages WHERE message_id = ?", (str(message_id),)
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get_by_id(self, message_id: UUID) -> Message | None:
        row = await self._get_row(message_id, self.database.require_connection())
        return self._to_domain(row) if row else None

    async def get_by_client_msg_id(
        self,
        account_id: str,
        client_msg_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> Message | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND client_msg_id = ?",
            (account_id, str(client_msg_id)),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def get_idempotency_record(
        self,
        account_id: str,
        client_msg_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> MessageIdempotencyRecord | None:
        """Read only the internal fields needed for T1 replay detection."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT message_id, trace_id, normalized_payload_hash "
            "FROM messages WHERE account_id = ? AND client_msg_id = ?",
            (account_id, str(client_msg_id)),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            return None
        return MessageIdempotencyRecord(
            message_id=_required_uuid(row["message_id"], "message_id"),
            trace_id=_required_uuid(row["trace_id"], "trace_id"),
            normalized_payload_hash=_row_value(row, "normalized_payload_hash"),
        )

    async def insert(
        self,
        message: Message,
        *,
        normalized_payload_hash: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> Message:
        conn = require_write_connection(connection)
        if message.sender.type is SenderType.PLAYER:
            if message.input_batch_id is None:
                raise DomainInvariantError("a new player message must reference an input batch")
            if message.client_msg_id is None:
                raise DomainInvariantError("a new player message must reference a client message")
            if normalized_payload_hash is None:
                raise DomainInvariantError(
                    "a new player message must contain a normalized payload hash"
                )
        if message.sender.type is SenderType.CHARACTER and (
            message.result_id is None or message.bubble_index is None
        ):
            raise DomainInvariantError("a new character message must reference a result bubble")
        await conn.execute(
            """INSERT INTO messages(
                message_id, account_id, conversation_id, sender_type, sender_id, text,
                images_json, client_msg_id, normalized_payload_hash, client_timestamp_utc,
                server_timestamp_utc, reply_to_message_id, trace_id, input_batch_id,
                result_id, bubble_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(message.message_id),
                message.account_id,
                message.conversation_id,
                message.sender.type.value,
                message.sender.id,
                message.text,
                as_json(message.images),
                str(message.client_msg_id) if message.client_msg_id else None,
                normalized_payload_hash,
                utc_text(message.client_timestamp_utc) if message.client_timestamp_utc else None,
                utc_text(message.server_timestamp_utc),
                str(message.reply_to_message_id) if message.reply_to_message_id else None,
                str(message.trace_id),
                str(message.input_batch_id) if message.input_batch_id else None,
                str(message.result_id) if message.result_id else None,
                message.bubble_index,
            ),
        )
        row = await self._get_row(message.message_id, conn)
        if row is None:
            raise RuntimeError("message was not persisted")
        stored = self._to_domain(row)
        if self.search_index is not None:
            with suppress(MemorySearchUnavailableError):
                await self.search_index.upsert_message(stored, connection=conn)
                # The FTS projection is rebuildable and is never authoritative.
        return stored

    async def list_conversation(
        self,
        account_id: str,
        conversation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND conversation_id = ? "
            "AND message_sequence > ? ORDER BY message_sequence ASC LIMIT ?",
            (account_id, conversation_id, after_sequence, limit),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_account(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        """Read the compatibility account-wide stream from the Runtime table."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND message_sequence > ? "
            "ORDER BY message_sequence ASC LIMIT ?",
            (account_id, after_sequence, limit),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_for_input_batches(
        self,
        account_id: str,
        conversation_id: str,
        input_batch_ids: tuple[UUID, ...],
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        """Read player messages linked to a frozen set of input batches."""

        if not input_batch_ids:
            return ()
        conn = get_connection(self.database, connection)
        placeholders = ", ".join("?" for _ in input_batch_ids)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND conversation_id = ? "
            f"AND input_batch_id IN ({placeholders}) AND sender_type = 'player' "
            "ORDER BY message_sequence ASC",
            (account_id, conversation_id, *(str(batch_id) for batch_id in input_batch_ids)),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_conversation_through(
        self,
        account_id: str,
        conversation_id: str,
        through_sequence: int,
        *,
        limit: int = 20,
        exclude_message_ids: tuple[UUID, ...] = (),
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        """Read a bounded historical suffix at an explicit frozen boundary."""

        boundary = require_sequence(through_sequence, "through_sequence")
        if limit <= 0:
            raise DomainInvariantError("limit must be positive")
        conn = get_connection(self.database, connection)
        parameters: list[object] = [account_id, conversation_id, boundary]
        exclusions = ""
        if exclude_message_ids:
            placeholders = ", ".join("?" for _ in exclude_message_ids)
            exclusions = f" AND message_id NOT IN ({placeholders})"
            parameters.extend(str(message_id) for message_id in exclude_message_ids)
        parameters.append(limit)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND conversation_id = ? "
            "AND message_sequence <= ?" + exclusions + " ORDER BY message_sequence DESC LIMIT ?",
            tuple(parameters),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in reversed(rows))

    async def list_conversation_range(
        self,
        account_id: str,
        conversation_id: str,
        first_sequence: int,
        last_sequence: int,
        *,
        limit: int = 100,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        """Read one bounded sealed segment in message order."""

        first = require_sequence(first_sequence, "first_sequence", minimum=1)
        last = require_sequence(last_sequence, "last_sequence", minimum=first)
        if limit <= 0:
            raise DomainInvariantError("limit must be positive")
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM messages WHERE account_id = ? AND conversation_id = ? "
            "AND message_sequence BETWEEN ? AND ? ORDER BY message_sequence ASC LIMIT ?",
            (account_id, conversation_id, first, last, limit),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_unsegmented_for_memory(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        through_sequence: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Message, ...]:
        """List conversation messages not covered by a durable memory segment."""

        conn = get_connection(self.database, connection)
        parameters: list[object] = [account_id, conversation_id]
        boundary_clause = ""
        if through_sequence is not None:
            boundary_clause = " AND m.message_sequence <= ?"
            parameters.append(require_sequence(through_sequence, "through_sequence"))
        parameters.append(character_id)
        cursor = await conn.execute(
            f"""SELECT m.* FROM messages AS m
               WHERE m.account_id = ? AND m.conversation_id = ?
                 {boundary_clause}
                 AND NOT EXISTS (
                     SELECT 1 FROM memory_segments AS s
                     WHERE s.account_id = m.account_id
                       AND s.conversation_id = m.conversation_id
                       AND s.character_id = ?
                       AND m.message_sequence BETWEEN s.first_message_sequence
                                                   AND s.last_message_sequence
                 )
               ORDER BY m.message_sequence ASC""",
            tuple(parameters),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def max_sequence(
        self,
        account_id: str,
        conversation_id: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        conn = get_connection(self.database, connection)
        if conversation_id is None:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(message_sequence), 0) AS value "
                "FROM messages WHERE account_id = ?",
                (account_id,),
            )
        else:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(message_sequence), 0) AS value FROM messages "
                "WHERE account_id = ? AND conversation_id = ?",
                (account_id, conversation_id),
            )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return int(row["value"]) if row else 0

    async def max_sequence_through(
        self,
        account_id: str,
        conversation_id: str,
        through_sequence: int,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        """Return the conversation's highest message sequence at a frozen boundary."""

        boundary = require_sequence(through_sequence, "through_sequence")
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(message_sequence), 0) AS value FROM messages "
            "WHERE account_id = ? AND conversation_id = ? AND message_sequence <= ?",
            (account_id, conversation_id, boundary),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return int(row["value"]) if row else 0


class InputBatchRepository:
    """Persistence and transition helpers for InputBatch."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> InputBatch:
        return InputBatch(
            input_batch_id=_required_uuid(row["input_batch_id"], "input_batch_id"),
            account_id=row["account_id"],
            conversation_id=row["conversation_id"],
            quiet_until_utc=_required_time(row["quiet_until_utc"], "quiet_until_utc"),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            status=row["status"],
            sealed_at_utc=_optional_time(row["sealed_at_utc"], "sealed_at_utc"),
            task_id=_optional_uuid(row["task_id"], "task_id"),
            first_message_sequence=row["first_message_sequence"],
            last_message_sequence=row["last_message_sequence"],
        )

    async def _get_row(
        self,
        input_batch_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM input_batches WHERE input_batch_id = ?", (str(input_batch_id),)
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        input_batch_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(input_batch_id, conn)
        return self._to_domain(row) if row else None

    async def get_collecting(
        self,
        account_id: str,
        conversation_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM input_batches WHERE account_id = ? AND conversation_id = ? "
            "AND status = 'collecting'",
            (account_id, conversation_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def list_collecting_due(
        self,
        account_id: str,
        now_utc: datetime,
        *,
        conversation_id: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[InputBatch, ...]:
        """List collecting batches whose quiet window has elapsed."""

        conn = get_connection(self.database, connection)
        parameters: tuple[object, ...]
        if conversation_id is None:
            sql = (
                "SELECT * FROM input_batches WHERE account_id = ? "
                "AND status = 'collecting' AND quiet_until_utc <= ? "
                "ORDER BY quiet_until_utc, first_message_sequence, created_at_utc"
            )
            parameters = (account_id, utc_text(require_utc(now_utc, "now_utc")))
        else:
            sql = (
                "SELECT * FROM input_batches WHERE account_id = ? AND conversation_id = ? "
                "AND status = 'collecting' AND quiet_until_utc <= ? "
                "ORDER BY quiet_until_utc, first_message_sequence, created_at_utc"
            )
            parameters = (
                account_id,
                conversation_id,
                utc_text(require_utc(now_utc, "now_utc")),
            )
        cursor = await conn.execute(sql, parameters)
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_waiting(
        self,
        account_id: str,
        conversation_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[InputBatch, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM input_batches WHERE account_id = ? AND conversation_id = ? "
            "AND status = 'waiting' ORDER BY first_message_sequence, created_at_utc",
            (account_id, conversation_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def list_for_task(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[InputBatch, ...]:
        """List every batch frozen into a task in player-message order."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM input_batches WHERE task_id = ? "
            "ORDER BY first_message_sequence, created_at_utc",
            (str(task_id),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def create(
        self,
        batch: InputBatch,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO input_batches(
                input_batch_id, account_id, conversation_id, status, quiet_until_utc,
                sealed_at_utc, task_id, first_message_sequence, last_message_sequence,
                created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(batch.input_batch_id),
                batch.account_id,
                batch.conversation_id,
                batch.status.value,
                utc_text(batch.quiet_until_utc),
                utc_text(batch.sealed_at_utc) if batch.sealed_at_utc else None,
                str(batch.task_id) if batch.task_id else None,
                batch.first_message_sequence,
                batch.last_message_sequence,
                utc_text(batch.created_at_utc),
                utc_text(batch.updated_at_utc),
            ),
        )
        stored = await self.get(batch.input_batch_id, connection=conn)
        if stored is None:
            raise RuntimeError("input batch was not persisted")
        return stored

    async def save(
        self,
        batch: InputBatch,
        *,
        expected_updated_at_utc: datetime | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        sql = (
            "UPDATE input_batches SET status = ?, quiet_until_utc = ?, sealed_at_utc = ?, "
            "task_id = ?, first_message_sequence = ?, last_message_sequence = ?, "
            "updated_at_utc = ? WHERE input_batch_id = ?"
        )
        parameters: tuple[object, ...] = (
            batch.status.value,
            utc_text(batch.quiet_until_utc),
            utc_text(batch.sealed_at_utc) if batch.sealed_at_utc else None,
            str(batch.task_id) if batch.task_id else None,
            batch.first_message_sequence,
            batch.last_message_sequence,
            utc_text(batch.updated_at_utc),
            str(batch.input_batch_id),
        )
        if expected_updated_at_utc is not None:
            sql += " AND updated_at_utc = ?"
            parameters += (
                utc_text(require_utc(expected_updated_at_utc, "expected_updated_at_utc")),
            )
        cursor = await conn.execute(sql, parameters)
        _check_rowcount(cursor.rowcount, "input batch")
        return batch

    async def append_message(
        self,
        input_batch_id: UUID,
        *,
        message_sequence: int,
        now_utc: datetime,
        quiet_window_seconds: int = QUIET_WINDOW_SECONDS,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        current = await self.get(input_batch_id, connection=conn)
        if current is None:
            raise LookupError("input_batch_not_found")
        updated = current.append_message(
            message_sequence=message_sequence,
            now_utc=now_utc,
            quiet_window_seconds=quiet_window_seconds,
        )
        return await self.save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def seal(
        self,
        input_batch_id: UUID,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        current = await self.get(input_batch_id, connection=conn)
        if current is None:
            raise LookupError("input_batch_not_found")
        updated = current.seal(now_utc=now_utc)
        return await self.save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def assign(
        self,
        input_batch_id: UUID,
        *,
        task_id: UUID,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        current = await self.get(input_batch_id, connection=conn)
        if current is None:
            raise LookupError("input_batch_not_found")
        updated = current.assign(task_id=task_id, now_utc=now_utc)
        return await self.save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def cover(
        self,
        input_batch_id: UUID,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        current = await self.get(input_batch_id, connection=conn)
        if current is None:
            raise LookupError("input_batch_not_found")
        updated = current.cover(now_utc=now_utc)
        return await self.save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def fail_terminally(
        self,
        input_batch_id: UUID,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> InputBatch:
        conn = require_write_connection(connection)
        current = await self.get(input_batch_id, connection=conn)
        if current is None:
            raise LookupError("input_batch_not_found")
        updated = current.fail_terminally(now_utc=now_utc)
        return await self.save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )


class ConversationTaskRepository:
    """Persistence, claiming, and recovery helpers for ConversationTask."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> ConversationTask:
        return ConversationTask(
            task_id=_required_uuid(row["task_id"], "task_id"),
            account_id=row["account_id"],
            conversation_id=row["conversation_id"],
            character_id=row["character_id"],
            input_max_message_sequence=int(row["input_max_message_sequence"]),
            context_max_message_sequence=int(row["context_max_message_sequence"]),
            world_state_version=int(row["world_state_version"]),
            character_state_version=int(row["character_state_version"]),
            context_version=row["context_version"],
            available_at_utc=_required_time(row["available_at_utc"], "available_at_utc"),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            trace_id=_required_uuid(row["trace_id"], "trace_id"),
            status=row["status"],
            attempt_count=int(row["attempt_count"]),
            lease_generation=int(row["lease_generation"]),
            lease_owner=row["lease_owner"],
            lease_until_utc=_optional_time(row["lease_until_utc"], "lease_until_utc"),
            last_error_code=row["last_error_code"],
        )

    async def _get_row(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM conversation_tasks WHERE task_id = ?", (str(task_id),)
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(task_id, conn)
        return self._to_domain(row) if row else None

    async def get_active_for_conversation(
        self,
        account_id: str,
        conversation_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask | None:
        """Return the durable active task guarded by the partial unique index."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM conversation_tasks WHERE account_id = ? AND conversation_id = ? "
            "AND status IN ('pending', 'processing', 'retry_wait', 'deferred') "
            "ORDER BY created_at_utc, task_id LIMIT 1",
            (account_id, conversation_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def create(
        self,
        task: ConversationTask,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO conversation_tasks(
                task_id, account_id, conversation_id, character_id, status, attempt_count,
                lease_generation, available_at_utc, lease_owner, lease_until_utc,
                input_max_message_sequence,
                context_max_message_sequence, world_state_version, character_state_version,
                context_version, last_error_code, created_at_utc, updated_at_utc, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._parameters(task),
        )
        stored = await self.get(task.task_id, connection=conn)
        if stored is None:
            raise RuntimeError("conversation task was not persisted")
        return stored

    @staticmethod
    def _parameters(task: ConversationTask) -> tuple[object, ...]:
        return (
            str(task.task_id),
            task.account_id,
            task.conversation_id,
            task.character_id,
            task.status.value,
            task.attempt_count,
            task.lease_generation,
            utc_text(task.available_at_utc),
            task.lease_owner,
            utc_text(task.lease_until_utc) if task.lease_until_utc else None,
            task.input_max_message_sequence,
            task.context_max_message_sequence,
            task.world_state_version,
            task.character_state_version,
            task.context_version,
            task.last_error_code,
            utc_text(task.created_at_utc),
            utc_text(task.updated_at_utc),
            str(task.trace_id),
        )

    async def _save(
        self,
        task: ConversationTask,
        *,
        expected_updated_at_utc: datetime | None,
        connection: aiosqlite.Connection,
    ) -> ConversationTask:
        sql = (
            "UPDATE conversation_tasks SET status = ?, attempt_count = ?, lease_generation = ?, "
            "available_at_utc = ?, "
            "lease_owner = ?, lease_until_utc = ?, input_max_message_sequence = ?, "
            "context_max_message_sequence = ?, world_state_version = ?, "
            "character_state_version = ?, context_version = ?, last_error_code = ?, "
            "updated_at_utc = ? WHERE task_id = ?"
        )
        parameters: tuple[object, ...] = (
            task.status.value,
            task.attempt_count,
            task.lease_generation,
            utc_text(task.available_at_utc),
            task.lease_owner,
            utc_text(task.lease_until_utc) if task.lease_until_utc else None,
            task.input_max_message_sequence,
            task.context_max_message_sequence,
            task.world_state_version,
            task.character_state_version,
            task.context_version,
            task.last_error_code,
            utc_text(task.updated_at_utc),
            str(task.task_id),
        )
        if expected_updated_at_utc is not None:
            sql += " AND updated_at_utc = ?"
            parameters += (
                utc_text(require_utc(expected_updated_at_utc, "expected_updated_at_utc")),
            )
        cursor = await connection.execute(sql, parameters)
        _check_rowcount(cursor.rowcount, "conversation task")
        stored = await self._get_row(task.task_id, connection)
        if stored is None:
            raise RuntimeError("conversation task disappeared after update")
        return self._to_domain(stored)

    async def recover_expired(
        self,
        now_utc: datetime,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        cursor = await conn.execute(
            "SELECT * FROM conversation_tasks WHERE status = 'processing' "
            "AND lease_until_utc IS NOT NULL AND lease_until_utc <= ?",
            (utc_text(now),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        recovered = 0
        for row in rows:
            current = self._to_domain(row)
            updated = current.recover_expired(now_utc=now)
            await self._save(
                updated,
                expected_updated_at_utc=current.updated_at_utc,
                connection=conn,
            )
            recovered += 1
        return recovered

    async def claim_next(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        account_id: str | None = None,
        conversation_id: str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask | None:
        if lease_seconds <= 0:
            raise DomainInvariantError("lease_seconds must be positive")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.claim_next(
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    account_id=account_id,
                    conversation_id=conversation_id,
                    connection=conn,
                )

        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        await self.recover_expired(now, connection=conn)
        conditions = [
            "status IN ('pending', 'retry_wait')",
            "available_at_utc <= ?",
            "NOT EXISTS (SELECT 1 FROM conversation_tasks AS active "
            "WHERE active.account_id = conversation_tasks.account_id "
            "AND active.conversation_id = conversation_tasks.conversation_id "
            "AND active.status = 'processing')",
        ]
        parameters: list[object] = [utc_text(now)]
        if account_id is not None:
            conditions.append("account_id = ?")
            parameters.append(account_id)
        if conversation_id is not None:
            conditions.append("conversation_id = ?")
            parameters.append(conversation_id)
        cursor = await conn.execute(
            "SELECT * FROM conversation_tasks WHERE "
            + " AND ".join(conditions)
            + " ORDER BY input_max_message_sequence, created_at_utc, task_id LIMIT 1",
            tuple(parameters),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            return None
        current = self._to_domain(row)
        claimed = current.claim(
            worker_id=worker_id,
            now_utc=now,
            lease_until_utc=now + timedelta(seconds=lease_seconds),
        )
        return await self._save(
            claimed,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def renew_lease(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        attempt_count: int,
        lease_generation: int,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask | None:
        """Extend one lease only when its complete fencing identity still matches."""

        if lease_seconds <= 0:
            raise DomainInvariantError("lease_seconds must be positive")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self._renew_lease_in_transaction(
                    task_id,
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    attempt_count=attempt_count,
                    lease_generation=lease_generation,
                    connection=conn,
                )
        return await self._renew_lease_in_transaction(
            task_id,
            worker_id=worker_id,
            now_utc=now_utc,
            lease_seconds=lease_seconds,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
            connection=require_write_connection(connection),
        )

    async def _renew_lease_in_transaction(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        attempt_count: int,
        lease_generation: int,
        connection: aiosqlite.Connection,
    ) -> ConversationTask | None:
        now = require_utc(now_utc, "now_utc")
        current = await self.get(task_id, connection=connection)
        if current is None or not current.has_valid_lease(
            worker_id=worker_id,
            now_utc=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        ):
            return None
        renewed = current.renew_lease(
            worker_id=worker_id,
            now_utc=now,
            lease_until_utc=now + timedelta(seconds=lease_seconds),
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            renewed,
            expected_updated_at_utc=current.updated_at_utc,
            connection=connection,
        )

    async def complete(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("conversation_task_not_found")
        updated = current.complete(
            worker_id=worker_id,
            now_utc=now_utc,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def retry_or_fail(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        available_at_utc: datetime,
        error_code: str,
        max_attempts: int,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("conversation_task_not_found")
        updated = current.retry_or_fail(
            worker_id=worker_id,
            now_utc=now_utc,
            available_at_utc=available_at_utc,
            error_code=error_code,
            max_attempts=max_attempts,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def fail(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        error_code: str,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("conversation_task_not_found")
        updated = current.fail(
            worker_id=worker_id,
            now_utc=now_utc,
            error_code=error_code,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def defer(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        reason_code: str,
        available_at_utc: datetime | None = None,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("conversation_task_not_found")
        updated = current.defer(
            worker_id=worker_id,
            now_utc=now_utc,
            reason_code=reason_code,
            available_at_utc=available_at_utc,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def resume(
        self,
        task_id: UUID,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> ConversationTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("conversation_task_not_found")
        updated = current.resume(now_utc=now_utc)
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )


class AgentResultRepository:
    """Persistence and one-shot decision updates for AgentResult."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> AgentResult:
        return AgentResult(
            result_id=_required_uuid(row["result_id"], "result_id"),
            task_id=_required_uuid(row["task_id"], "task_id"),
            attempt_no=int(row["attempt_no"]),
            agent_id=row["agent_id"],
            agent_kind=row["agent_kind"],
            invocation_id=_required_uuid(row["invocation_id"], "invocation_id"),
            result_kind=row["result_kind"],
            schema_version=row["schema_version"],
            context_version=row["context_version"],
            payload_json=row["payload_json"],
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            status=row["status"],
            decision_code=row["decision_code"],
            decided_at_utc=_optional_time(row["decided_at_utc"], "decided_at_utc"),
        )

    async def _get_row(
        self,
        result_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM agent_results WHERE result_id = ?", (str(result_id),)
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        result_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> AgentResult | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(result_id, conn)
        return self._to_domain(row) if row else None

    async def list_for_task(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[AgentResult, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM agent_results WHERE task_id = ? ORDER BY attempt_no",
            (str(task_id),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def get_for_task_attempt(
        self,
        task_id: UUID,
        attempt_no: int,
        connection: aiosqlite.Connection | None = None,
    ) -> AgentResult | None:
        """Read the idempotent result slot for one Task attempt."""

        attempt = require_sequence(attempt_no, "attempt_no")
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM agent_results WHERE task_id = ? AND attempt_no = ?",
            (str(task_id), attempt),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def insert(
        self,
        result: AgentResult,
        *,
        source: str = "agent_run",
        connection: aiosqlite.Connection | None = None,
    ) -> AgentResult:
        conn = require_write_connection(connection)
        source = require_non_empty(source, "source")
        await conn.execute(
            """INSERT INTO agent_results(
                result_id, task_id, attempt_no, agent_id, agent_kind, invocation_id,
                result_kind, schema_version, context_version, payload_json, status,
                decision_code, created_at_utc, decided_at_utc, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(result.result_id),
                str(result.task_id),
                result.attempt_no,
                result.agent_id,
                result.agent_kind,
                str(result.invocation_id),
                result.result_kind,
                result.schema_version,
                result.context_version,
                result.payload_json,
                result.status.value,
                result.decision_code,
                utc_text(result.created_at_utc),
                utc_text(result.decided_at_utc) if result.decided_at_utc else None,
                source,
            ),
        )
        stored = await self.get(result.result_id, connection=conn)
        if stored is None:
            raise RuntimeError("Agent result was not persisted")
        return stored

    async def save_decision(
        self,
        result: AgentResult,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> AgentResult:
        if result.status is AgentResultStatus.PENDING:
            raise DomainInvariantError("a pending result cannot be saved as a decision")
        conn = require_write_connection(connection)
        cursor = await conn.execute(
            "UPDATE agent_results SET status = ?, decision_code = ?, decided_at_utc = ? "
            "WHERE result_id = ? AND status = 'pending'",
            (
                result.status.value,
                result.decision_code,
                utc_text(result.decided_at_utc) if result.decided_at_utc else None,
                str(result.result_id),
            ),
        )
        _check_rowcount(cursor.rowcount, "Agent result decision")
        return result

    async def has_approved(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> bool:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT 1 FROM agent_results WHERE task_id = ? AND status = 'approved' LIMIT 1",
            (str(task_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return row is not None


__all__ = [
    "AgentResultRepository",
    "CharacterStateRepository",
    "ConversationParticipantRepository",
    "ConversationTaskRepository",
    "InputBatchRepository",
    "MessageIdempotencyRecord",
    "RuntimeConversationRepository",
    "RuntimeMessageRepository",
    "WorldStateRepository",
]
