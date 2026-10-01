"""Read-only conversation synchronization workflow."""

from __future__ import annotations

import logging
from time import perf_counter

from echo_server.domain.messages import ConversationSyncQuery, MessageBatch, SyncMessagesQuery
from echo_server.observability.logging import get_logger, log_event
from echo_server.runtime.common import (
    decode_conversation_cursor,
    decode_cursor,
    encode_conversation_cursor,
    encode_cursor,
)
from echo_server.runtime.common import duration_ms as _duration_ms
from echo_server.runtime.errors import (
    DatabaseUnavailableError,
    InvalidCursorError,
    UnknownConversationError,
)
from echo_server.runtime.modules import ConversationModule

logger = get_logger("runtime")


class ConversationSyncService:
    def __init__(self, runtime: ConversationModule) -> None:
        self.runtime = runtime

    async def sync_messages(self, query: SyncMessagesQuery) -> MessageBatch:
        await self.runtime.ensure_started()
        started_at = perf_counter()
        try:
            sequence = decode_cursor(query.since)
            messages = await self.runtime.runtime_messages.list_account(
                query.account_id,
                after_sequence=sequence,
                limit=query.limit,
            )
            next_sequence = messages[-1].message_sequence if messages else sequence
            batch = MessageBatch(messages=messages, next_cursor=encode_cursor(next_sequence))
            log_event(
                logger,
                logging.DEBUG,
                "message.sync_completed",
                batch_size=len(messages),
                duration_ms=_duration_ms(started_at),
            )
            return batch
        except InvalidCursorError as exc:
            log_event(
                logger,
                logging.WARNING,
                "message.sync_failed",
                error_code=exc.code,
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "message.sync_failed",
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("messages could not be read") from exc

    async def sync_conversation_messages(
        self,
        query: ConversationSyncQuery,
    ) -> MessageBatch:
        """Read an incremental message stream scoped to one conversation."""

        await self.runtime.ensure_started()
        started_at = perf_counter()
        try:
            if (
                await self.runtime.runtime_conversations.get(
                    query.account_id,
                    query.conversation_id,
                )
                is None
            ):
                raise UnknownConversationError(query.conversation_id)

            sequence = decode_conversation_cursor(
                query.since,
                account_id=query.account_id,
                conversation_id=query.conversation_id,
            )
            messages = await self.runtime.runtime_messages.list_conversation(
                query.account_id,
                query.conversation_id,
                after_sequence=sequence,
                limit=query.limit,
            )
            next_sequence = messages[-1].message_sequence if messages else sequence
            batch = MessageBatch(
                messages=messages,
                next_cursor=encode_conversation_cursor(
                    query.account_id,
                    query.conversation_id,
                    next_sequence,
                ),
            )
            log_event(
                logger,
                logging.DEBUG,
                "conversation.message.sync_completed",
                account_id=query.account_id,
                conversation_id=query.conversation_id,
                batch_size=len(messages),
                duration_ms=_duration_ms(started_at),
            )
            return batch
        except (InvalidCursorError, UnknownConversationError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "conversation.message.sync_failed",
                account_id=query.account_id,
                conversation_id=query.conversation_id,
                error_code=exc.code,
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "conversation.message.sync_failed",
                account_id=query.account_id,
                conversation_id=query.conversation_id,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("conversation messages could not be read") from exc


__all__ = ["ConversationSyncService"]
