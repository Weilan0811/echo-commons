class BusinessError(ValueError):
    code = "invalid_operation"


class NotFoundError(BusinessError):
    code = "not_found"


class ConflictError(BusinessError):
    code = "conflict"


class IdempotencyConflict(ConflictError):
    code = "idempotency_conflict"


class CharacterNotReady(ConflictError):
    code = "character_memory_not_ready"


class MembershipVersionConflict(ConflictError):
    code = "membership_version_conflict"


class MembershipIntervalConflict(ConflictError):
    code = "membership_interval_conflict"


class ConversationArchived(ConflictError):
    code = "conversation_archived"


class InvalidCursor(ValueError):
    code = "invalid_cursor"
