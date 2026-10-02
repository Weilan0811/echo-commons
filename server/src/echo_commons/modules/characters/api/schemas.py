from datetime import datetime

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.characters.domain.instance import AvailabilityStatus


class CreateCharacter(RequestModel):
    blueprint_id: str = Field(min_length=1)
    character_id: str | None = Field(default=None, min_length=1)


class BlueprintView(BaseModel):
    blueprint_id: str
    display_name: str
    content_version: str
    status: str


class CharacterView(BaseModel):
    character_id: str
    community_id: str
    blueprint_id: str
    blueprint_version: str
    availability_status: AvailabilityStatus
    availability_version: int
    created_at_utc: datetime
