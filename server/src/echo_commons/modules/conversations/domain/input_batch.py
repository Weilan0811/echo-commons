from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from echo_commons.modules.conversations.domain.message import Message, MessageVisibility
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class InputBatch:
    input_batch_id: str
    community_id: str
    conversation_id: str
    sender: ActorRef
    visibility: MessageVisibility
    audience: tuple[str, ...]
    status: str
    quiet_until_utc: datetime
    sealed_at_utc: datetime | None
    origin_turn_id: str | None
    created_at_utc: datetime
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        if self.status not in ("collecting", "sealed") or (self.status == "sealed") != (
            self.sealed_at_utc is not None
        ):
            raise ValueError("Input collection status and sealed time are inconsistent")

    def accepts(self, message: Message) -> bool:
        return (
            self.status == "collecting"
            and message.created_at_utc < self.quiet_until_utc
            and (
                self.community_id,
                self.conversation_id,
                self.sender,
                self.visibility,
                self.audience,
            )
            == (
                message.community_id,
                message.conversation_id,
                message.sender,
                message.visibility,
                message.audience,
            )
        )
