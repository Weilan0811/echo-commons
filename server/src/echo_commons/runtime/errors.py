from __future__ import annotations


class RuntimeErrorBase(Exception):
    """Base class for errors that can be mapped to a stable public code."""

    code = "runtime_error"


class UnknownConversationError(RuntimeErrorBase):
    code = "conversation_not_found"


class IdempotencyConflictError(RuntimeErrorBase):
    code = "idempotency_conflict"


class InvalidCursorError(RuntimeErrorBase):
    code = "invalid_cursor"


class DatabaseUnavailableError(RuntimeErrorBase):
    code = "service_unavailable"


class UnsupportedCapabilityError(RuntimeErrorBase):
    code = "invalid_request"


class InvalidAgentRunError(RuntimeErrorBase):
    code = "agent_run_invalid"


class LeaseLostError(RuntimeErrorBase):
    code = "lease_lost"


class LeaseHeartbeatError(LeaseLostError):
    code = "lease_heartbeat_failed"


__all__ = [
    "DatabaseUnavailableError",
    "IdempotencyConflictError",
    "InvalidAgentRunError",
    "InvalidCursorError",
    "LeaseHeartbeatError",
    "LeaseLostError",
    "RuntimeErrorBase",
    "UnknownConversationError",
    "UnsupportedCapabilityError",
]
