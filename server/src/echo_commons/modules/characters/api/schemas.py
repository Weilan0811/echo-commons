from datetime import datetime

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.characters.domain.instance import (
    AvailabilityStatus,
    MemoryMode,
    MemoryStatus,
)


class CreateCharacter(RequestModel):
    person_id: str | None = Field(default=None, min_length=1)
    player_id: str = Field(min_length=1)
    blueprint_id: str = Field(min_length=1)
    character_id: str | None = Field(default=None, min_length=1)
    memory_mode: MemoryMode = MemoryMode.SIMPLE


class RetryMemory(RequestModel):
    player_id: str = Field(min_length=1)


class UpdateCharacterAppearance(RequestModel):
    player_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    avatar_asset_id: str | None


class BlueprintView(BaseModel):
    blueprint_id: str
    display_name: str
    content_version: str
    status: str
    avatar_url: str | None = None
    illustration_url: str | None = None


class CharacterView(BaseModel):
    display_name: str
    avatar_url: str | None = None
    illustration_url: str | None = None
    avatar_asset_id: str | None = None
    appearance_version: int = 0
    character_id: str
    community_id: str
    blueprint_id: str
    blueprint_version: str
    availability_status: AvailabilityStatus
    availability_version: int
    created_at_utc: datetime
    memory_mode: MemoryMode
    memory_status: MemoryStatus
    memory_phase: str | None = None
