"""Deterministic input-batch selection for the S2.5 T2 scheduler."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from echo_server.domain.errors import DomainInvariantError, require_non_empty
from echo_server.domain.input_batch import InputBatch, InputBatchStatus
from echo_server.domain.messages import Message, SenderType


@dataclass(frozen=True, slots=True)
class InputPreparationResult:
    """The accepted waiting prefix and an optional reason for an unaccepted tail."""

    accepted_batches: tuple[InputBatch, ...]
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_batches", tuple(self.accepted_batches))
        if self.blocked_reason is not None:
            object.__setattr__(
                self,
                "blocked_reason",
                require_non_empty(self.blocked_reason, "blocked_reason"),
            )

    @property
    def input_max_message_sequence(self) -> int | None:
        if not self.accepted_batches:
            return None
        return self.accepted_batches[-1].last_message_sequence


class InputPreparation(Protocol):
    """Pure port for selecting a contiguous, capacity-safe batch prefix."""

    def prepare(
        self,
        batches: tuple[InputBatch, ...],
        messages: tuple[Message, ...],
    ) -> InputPreparationResult:
        """Return the prefix that can be frozen into one ConversationTask."""


class OfflineInputPreparation:
    """Offline substitute with optional deterministic message/character limits.

    With no limits configured, all valid waiting batches are accepted.  Limits
    are intentionally constructor arguments rather than product settings until
    the later Memory and model-cost work defines the real policy.
    """

    def __init__(
        self,
        *,
        max_messages: int | None = None,
        max_characters: int | None = None,
    ) -> None:
        if max_messages is not None and max_messages <= 0:
            raise DomainInvariantError("max_messages must be positive")
        if max_characters is not None and max_characters <= 0:
            raise DomainInvariantError("max_characters must be positive")
        self.max_messages = max_messages
        self.max_characters = max_characters

    def prepare(
        self,
        batches: tuple[InputBatch, ...],
        messages: tuple[Message, ...],
    ) -> InputPreparationResult:
        ordered_batches = tuple(batches)
        messages_by_batch: dict[UUID, list[Message]] = defaultdict(list)
        for message in messages:
            if message.input_batch_id is not None:
                messages_by_batch[message.input_batch_id].append(message)
        for batch_messages in messages_by_batch.values():
            batch_messages.sort(key=lambda message: message.message_sequence)

        accepted: list[InputBatch] = []
        total_messages = 0
        total_characters = 0
        previous_last_sequence: int | None = None

        for batch in ordered_batches:
            if batch.status is not InputBatchStatus.WAITING:
                return InputPreparationResult(tuple(accepted), "input_batch_not_waiting")
            batch_messages = messages_by_batch.get(batch.input_batch_id, [])
            if not batch_messages:
                return InputPreparationResult(tuple(accepted), "input_batch_not_ready")
            if (
                batch.first_message_sequence != batch_messages[0].message_sequence
                or batch.last_message_sequence != batch_messages[-1].message_sequence
            ):
                return InputPreparationResult(tuple(accepted), "input_batch_not_ready")
            if any(
                message.sender.type is not SenderType.PLAYER
                or message.input_batch_id != batch.input_batch_id
                for message in batch_messages
            ):
                return InputPreparationResult(tuple(accepted), "input_batch_not_ready")
            if (
                previous_last_sequence is not None
                and batch.first_message_sequence <= previous_last_sequence
            ):
                return InputPreparationResult(tuple(accepted), "input_batch_order_invalid")

            batch_message_count = len(batch_messages)
            batch_character_count = sum(len(message.text) for message in batch_messages)
            exceeds_messages = (
                self.max_messages is not None
                and total_messages + batch_message_count > self.max_messages
            )
            exceeds_characters = (
                self.max_characters is not None
                and total_characters + batch_character_count > self.max_characters
            )
            if exceeds_messages or exceeds_characters:
                reason = "input_capacity_exceeded"
                return InputPreparationResult(tuple(accepted), reason)

            accepted.append(batch)
            total_messages += batch_message_count
            total_characters += batch_character_count
            previous_last_sequence = batch.last_message_sequence

        return InputPreparationResult(tuple(accepted))


__all__ = [
    "InputPreparation",
    "InputPreparationResult",
    "OfflineInputPreparation",
]
