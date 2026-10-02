from datetime import datetime

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.communities.domain import CommunityStatus


class CreateCommunity(RequestModel):
    name: str = Field(min_length=1)
    timezone: str = "UTC"
    community_id: str | None = Field(default=None, min_length=1)
    world_time_utc: datetime | None = None


class RegisterPlayer(RequestModel):
    display_name: str = Field(min_length=1)
    player_id: str | None = Field(default=None, min_length=1)


class CommunityView(BaseModel):
    community_id: str
    name: str
    timezone: str
    world_time_utc: datetime
    status: CommunityStatus
    state_version: int
    created_at_utc: datetime
    updated_at_utc: datetime


class PlayerView(BaseModel):
    player_id: str
    display_name: str
    created_at_utc: datetime
