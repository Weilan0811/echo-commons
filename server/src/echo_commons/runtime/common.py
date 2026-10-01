from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter

from echo_commons.domain.messages import SubmitMessageCommand
from echo_commons.runtime.errors import InvalidCursorError
from echo_commons.store.repository_support import utc_text


def utc_now() -> datetime:
    return datetime.now(UTC)


def duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def normalize_payload_hash(command: SubmitMessageCommand) -> str:
    """Hash exact player text and canonical transport fields without rewriting text."""

    local_timestamp = command.local_timestamp
    timestamp_text = utc_text(local_timestamp) if local_timestamp else None
    payload = {
        "conversationId": command.conversation_id,
        "playerText": command.player_text,
        "images": list(command.images),
        "localTimestamp": timestamp_text,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def encode_cursor(sequence: int) -> str:
    if sequence < 0:
        raise InvalidCursorError("cursor must not be negative")
    return base64.urlsafe_b64encode(f"v1:{sequence}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
        version, value = decoded.split(":", 1)
        if version != "v1" or not value.isdigit():
            raise ValueError
        sequence = int(value)
        if sequence < 0:
            raise ValueError
        return sequence
    except (ValueError, UnicodeError, base64.binascii.Error) as exc:
        raise InvalidCursorError("invalid cursor") from exc


def encode_conversation_cursor(account_id: str, conversation_id: str, sequence: int) -> str:
    """Encode an opaque cursor bound to one account and conversation."""

    if sequence < 0:
        raise InvalidCursorError("cursor must not be negative")
    payload = json.dumps(
        {
            "accountId": account_id,
            "conversationId": conversation_id,
            "afterSequence": sequence,
            "version": 2,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(b"v2:" + payload).decode().rstrip("=")


def decode_conversation_cursor(
    cursor: str | None,
    *,
    account_id: str,
    conversation_id: str,
) -> int:
    """Decode and scope-check a conversation cursor."""

    if cursor is None or cursor == "":
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        prefix, encoded_payload = decoded.split(b":", 1)
        if prefix != b"v2":
            raise ValueError
        payload = json.loads(encoded_payload.decode())
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise ValueError
        if payload.get("accountId") != account_id:
            raise ValueError
        if payload.get("conversationId") != conversation_id:
            raise ValueError
        sequence = payload.get("afterSequence")
        if type(sequence) is not int or sequence < 0:
            raise ValueError
        return sequence
    except (KeyError, TypeError, ValueError, UnicodeError, base64.binascii.Error) as exc:
        raise InvalidCursorError("invalid conversation cursor") from exc


__all__ = [
    "decode_conversation_cursor",
    "decode_cursor",
    "duration_ms",
    "encode_conversation_cursor",
    "encode_cursor",
    "normalize_payload_hash",
    "utc_now",
]
