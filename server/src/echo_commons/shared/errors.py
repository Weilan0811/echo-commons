class BusinessError(ValueError):
    code = "invalid_operation"


class NotFoundError(BusinessError):
    code = "not_found"


class ConflictError(BusinessError):
    code = "conflict"
