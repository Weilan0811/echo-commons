from dataclasses import dataclass

from echo_commons.modules.social.domain import SocialChain


@dataclass(frozen=True, slots=True)
class ContinuationPolicy:
    max_messages: int = 3
    max_tasks: int = 6

    def __post_init__(self) -> None:
        if self.max_messages < 1 or self.max_tasks < 1:
            raise ValueError("Social chain limits must be positive")

    @staticmethod
    def stop_reason(chain: SocialChain) -> str | None:
        if chain.status != "active":
            return chain.stop_reason
        if chain.message_count >= chain.max_messages:
            return "message_limit"
        if chain.task_count >= chain.max_tasks:
            return "task_limit"
        return None
