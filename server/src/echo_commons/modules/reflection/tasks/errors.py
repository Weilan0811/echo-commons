from echo_commons.shared.errors import BusinessError


class ReflectionReviewError(BusinessError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
