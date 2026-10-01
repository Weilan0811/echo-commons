"""T1 message intake and quiet-window batch sealing."""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from uuid import UUID, uuid4

import aiosqlite

from echo_server.domain.input_batch import InputBatch
from echo_server.domain.messages import Message, MessageReceipt, SubmitMessageCommand
from echo_server.observability.logging import get_logger, log_event
from echo_server.observability.trace import safe_trace_payload
from echo_server.runtime.common import duration_ms as _duration_ms
from echo_server.runtime.common import normalize_payload_hash
from echo_server.runtime.errors import (
    DatabaseUnavailableError,
    IdempotencyConflictError,
    UnknownConversationError,
    UnsupportedCapabilityError,
)
from echo_server.runtime.modules import ConversationModule

logger = get_logger("runtime")


class ConversationIntakeService:
    def __init__(self, runtime: ConversationModule) -> None:
        self.runtime = runtime

    async def submit_message(self, command: SubmitMessageCommand) -> MessageReceipt:
        """Persist one player message through the canonical T1 path.

        The public endpoint uses this method.  It deliberately writes only
        Conversation messages and input batches; it never creates a separate turn record.
        """

        await self.runtime.ensure_started()
        correlation_id = command.trace_id or uuid4()
        started_at = perf_counter()
        if command.images:
            log_event(
                logger,
                logging.WARNING,
                "message.rejected",
                correlation_id=correlation_id,
                client_msg_id=command.client_msg_id,
                error_code="unsupported_images",
                duration_ms=_duration_ms(started_at),
            )
            raise UnsupportedCapabilityError("images are not implemented")

        payload_hash = normalize_payload_hash(command)
        now = self.runtime.clock()
        replay_receipt: MessageReceipt | None = None
        message_id: UUID | None = None
        input_batch_id: UUID | None = None
        batch_created = False
        try:
            async with self.runtime.database.transaction(immediate=True) as connection:
                if (
                    await self.runtime.runtime_conversations.get(
                        command.account_id, command.conversation_id, connection
                    )
                    is None
                ):
                    raise UnknownConversationError(command.conversation_id)

                existing = await self.runtime.runtime_messages.get_idempotency_record(
                    command.account_id, command.client_msg_id, connection
                )
                if existing is not None:
                    if existing.normalized_payload_hash != payload_hash:
                        raise IdempotencyConflictError(command.client_msg_id)
                    await self.runtime.task_traces.enqueue(
                        trace_id=uuid4(),
                        correlation_id=existing.trace_id,
                        kind="message.idempotent_replay",
                        entity_type="message",
                        entity_id=str(existing.message_id),
                        payload=safe_trace_payload("message.idempotent_replay"),
                        created_at=now,
                        connection=connection,
                    )
                    replay_receipt = MessageReceipt(
                        True,
                        existing.message_id,
                        command.client_msg_id,
                        existing.trace_id,
                    )
                else:
                    batch = await self.runtime.input_batches.get_collecting(
                        command.account_id, command.conversation_id, connection
                    )
                    if batch is not None and batch.is_quiet_elapsed(now_utc=now):
                        await self.runtime.input_batches.seal(
                            batch.input_batch_id,
                            now_utc=now,
                            connection=connection,
                        )
                        await self.runtime.task_traces.enqueue(
                            trace_id=uuid4(),
                            correlation_id=correlation_id,
                            kind="input_batch.sealed",
                            entity_type="input_batch",
                            entity_id=str(batch.input_batch_id),
                            payload=safe_trace_payload("input_batch.sealed"),
                            created_at=now,
                            connection=connection,
                        )
                        batch = None

                    if batch is None:
                        batch = InputBatch.start(
                            input_batch_id=uuid4(),
                            account_id=command.account_id,
                            conversation_id=command.conversation_id,
                            now_utc=now,
                            quiet_window_seconds=self.runtime.settings.quiet_window_seconds,
                        )
                        await self.runtime.input_batches.create(batch, connection=connection)
                        batch_created = True

                    message_id = uuid4()
                    stored_message = await self.runtime.runtime_messages.insert(
                        Message.player(
                            # SQLite assigns the authoritative sequence during insert.
                            message_sequence=0,
                            message_id=message_id,
                            account_id=command.account_id,
                            conversation_id=command.conversation_id,
                            sender_id=command.account_id,
                            text=command.player_text,
                            images=command.images,
                            client_msg_id=command.client_msg_id,
                            client_timestamp_utc=command.local_timestamp,
                            server_timestamp_utc=now,
                            input_batch_id=batch.input_batch_id,
                            reply_to_message_id=None,
                            trace_id=correlation_id,
                        ),
                        normalized_payload_hash=payload_hash,
                        connection=connection,
                    )
                    input_batch_id = batch.input_batch_id
                    await self.runtime.input_batches.append_message(
                        batch.input_batch_id,
                        message_sequence=stored_message.message_sequence,
                        now_utc=now,
                        quiet_window_seconds=self.runtime.settings.quiet_window_seconds,
                        connection=connection,
                    )
                    await self.runtime.task_traces.enqueue(
                        trace_id=uuid4(),
                        correlation_id=correlation_id,
                        kind="input_batch.created" if batch_created else "input_batch.extended",
                        entity_type="input_batch",
                        entity_id=str(batch.input_batch_id),
                        payload=safe_trace_payload(
                            "input_batch.created" if batch_created else "input_batch.extended"
                        ),
                        created_at=now,
                        connection=connection,
                    )
                    await self.runtime.task_traces.enqueue(
                        trace_id=uuid4(),
                        correlation_id=correlation_id,
                        kind="message.accepted",
                        entity_type="message",
                        entity_id=str(message_id),
                        payload=safe_trace_payload("message.accepted"),
                        created_at=now,
                        connection=connection,
                    )
            if replay_receipt is not None:
                log_event(
                    logger,
                    logging.INFO,
                    "message.idempotent_replay",
                    correlation_id=replay_receipt.trace_id,
                    message_id=replay_receipt.message_id,
                    client_msg_id=replay_receipt.client_msg_id,
                    duration_ms=_duration_ms(started_at),
                )
                return replay_receipt

            if self.runtime.wakeup is not None:
                self.runtime.wakeup.set()
            assert message_id is not None
            assert input_batch_id is not None
            log_event(
                logger,
                logging.INFO,
                "message.accepted",
                correlation_id=correlation_id,
                message_id=message_id,
                client_msg_id=command.client_msg_id,
                input_batch_id=input_batch_id,
                duration_ms=_duration_ms(started_at),
            )
            return MessageReceipt(True, message_id, command.client_msg_id, correlation_id)
        except (UnknownConversationError, IdempotencyConflictError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "message.rejected",
                correlation_id=correlation_id,
                client_msg_id=command.client_msg_id,
                error_code=exc.code,
                duration_ms=_duration_ms(started_at),
            )
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "message.persistence_failed",
                correlation_id=correlation_id,
                client_msg_id=command.client_msg_id,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("S2.5 message was not persisted") from exc

    async def _seal_due_input_batches_in_transaction(
        self,
        account_id: str,
        conversation_id: str | None,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> int:
        due_batches = await self.runtime.input_batches.list_collecting_due(
            account_id,
            now,
            conversation_id=conversation_id,
            connection=connection,
        )
        sealed_count = 0
        for batch in due_batches:
            await self.runtime.input_batches.seal(
                batch.input_batch_id,
                now_utc=now,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=correlation_id,
                kind="input_batch.sealed",
                entity_type="input_batch",
                entity_id=str(batch.input_batch_id),
                payload=safe_trace_payload("input_batch.sealed"),
                created_at=now,
                connection=connection,
            )
            sealed_count += 1
        return sealed_count

    async def seal_due_input_batches(
        self,
        *,
        account_id: str | None = None,
        conversation_id: str | None = None,
    ) -> int:
        """Seal S2.5 collecting batches whose quiet windows have elapsed."""

        await self.runtime.ensure_started()
        account = account_id or self.runtime.settings.account_id
        now = self.runtime.clock()
        correlation_id = uuid4()
        started_at = perf_counter()
        sealed_count = 0
        try:
            async with self.runtime.database.transaction(immediate=True) as connection:
                sealed_count = await self._seal_due_input_batches_in_transaction(
                    account,
                    conversation_id,
                    now,
                    correlation_id,
                    connection,
                )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "input_batch.seal_failed",
                correlation_id=correlation_id,
                account_id=account,
                conversation_id=conversation_id,
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("S2.5 input batches could not be sealed") from exc

        if sealed_count and self.runtime.wakeup is not None:
            self.runtime.wakeup.set()
        log_event(
            logger,
            logging.INFO,
            "input_batch.sealed_due",
            correlation_id=correlation_id,
            account_id=account,
            conversation_id=conversation_id,
            batch_count=sealed_count,
            duration_ms=_duration_ms(started_at),
        )
        return sealed_count


__all__ = ["ConversationIntakeService"]
