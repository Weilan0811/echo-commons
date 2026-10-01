"""Deterministic sealing of unsegmented conversation messages."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from echo_server.domain.errors import DomainInvariantError, require_non_empty, require_utc
from echo_server.domain.memory import MemorySegment, MemorySegmentStatus
from echo_server.domain.messages import Message
from echo_server.store.database import Database
from echo_server.store.memory_provenance import MemoryProvenanceRepository
from echo_server.store.memory_repositories import MemorySegmentRepository
from echo_server.store.runtime_repositories import (
    ConversationParticipantRepository,
    RuntimeConversationRepository,
    RuntimeMessageRepository,
)


class MemorySegmentSealingService:
    """Create one stable sealed source interval without invoking an Agent."""

    def __init__(
        self,
        database: Database,
        conversations: RuntimeConversationRepository,
        messages: RuntimeMessageRepository,
        segments: MemorySegmentRepository,
        participants: ConversationParticipantRepository,
    ) -> None:
        self.database = database
        self.conversations = conversations
        self.messages = messages
        self.segments = segments
        self.participants = participants

    async def seal_unsegmented_messages(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        through_sequence: int | None = None,
        now_utc: datetime | None = None,
    ) -> MemorySegment | None:
        """Seal the currently uncovered contiguous suffix for one conversation.

        The caller chooses *when* to call this method.  It deliberately does
        not enqueue Reflection or mutate InputBatch state.
        """

        account = require_non_empty(account_id, "account_id")
        conversation = require_non_empty(conversation_id, "conversation_id")
        character = require_non_empty(character_id, "character_id")
        sealed_at = require_utc(now_utc or datetime.now(UTC), "now_utc")
        async with self.database.transaction(immediate=True) as connection:
            stored_conversation = await self.conversations.get(
                account,
                conversation,
                connection=connection,
            )
            if stored_conversation is None:
                raise LookupError("conversation_not_found")
            active_participants = await self.participants.list_active(
                account,
                conversation,
                connection=connection,
            )
            if len(active_participants) != 1 or active_participants[0].character_id != character:
                raise DomainInvariantError("conversation participant does not match seal target")
            messages = await self.messages.list_unsegmented_for_memory(
                account,
                conversation,
                character,
                through_sequence=through_sequence,
                connection=connection,
            )
            if not messages:
                return None

            existing = await self.segments.list_for_scope(
                account,
                conversation,
                character,
                connection=connection,
            )
            start_sequence = messages[0].message_sequence
            later_segment_starts = sorted(
                segment.first_message_sequence
                for segment in existing
                if segment.first_message_sequence > start_sequence
            )
            if later_segment_starts:
                stop_before = later_segment_starts[0]
                messages = tuple(
                    message for message in messages if message.message_sequence < stop_before
                )
                if not messages:
                    return None

            provenance = MemoryProvenanceRepository()
            messages = await provenance.complete_reply_prefix(messages, connection=connection)
            if not messages:
                return None

            first = messages[0].message_sequence
            last = messages[-1].message_sequence
            source_version = _source_version(messages)
            segment = MemorySegment(
                segment_id=uuid4(),
                account_id=account,
                conversation_id=conversation,
                character_id=character,
                first_message_sequence=first,
                last_message_sequence=last,
                status=MemorySegmentStatus.SEALED,
                source_version=source_version,
                sealed_at_utc=sealed_at,
                created_at_utc=sealed_at,
                updated_at_utc=sealed_at,
            )
            await self.segments.create(segment, connection=connection)
            await provenance.bind_segment_thoughts(segment, connection=connection)
            return await self.segments.get(segment.segment_id, connection=connection)


def _source_version(messages: tuple[Message, ...]) -> str:
    digest = hashlib.sha256()
    for message in messages:
        digest.update(f"{message.message_sequence}:{message.message_id}".encode())
        digest.update(b"\n")
    return digest.hexdigest()[:16]


__all__ = ["MemorySegmentSealingService"]
