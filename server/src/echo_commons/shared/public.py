from pydantic import BaseModel

from echo_commons.shared.message_sources import MessageSource


class PublicDisplay(BaseModel):
    actor: MessageSource
    display_name: str
    avatar_url: str | None = None
    illustration_url: str | None = None
