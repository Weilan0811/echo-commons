from datetime import datetime

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.communities.domain import CommunityStatus


class CreateCommunity(RequestModel):
    player_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    timezone: str = "UTC"
    community_id: str | None = Field(default=None, min_length=1)
    world_time_utc: datetime | None = None
    cover_kind: str | None = None
    cover_ref: str | None = None


class RegisterPlayer(RequestModel):
    display_name: str = Field(min_length=1)
    player_id: str | None = Field(default=None, min_length=1)


class UpdateCommunityStatus(RequestModel):
    player_id: str = Field(min_length=1)
    status: CommunityStatus
    expected_version: int = Field(ge=0)


class UpdateCommunityAppearance(RequestModel):
    player_id: str = Field(min_length=1)
    expected_version: int = Field(ge=0)
    cover_kind: str | None
    cover_ref: str | None


class CommunityView(BaseModel):
    cover_kind: str | None = None
    cover_ref: str | None = None
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


class CommunityCapabilities(BaseModel):
    can_change_cover: bool
    can_change_status: bool


class PublicCommunityView(CommunityView):
    capabilities: CommunityCapabilities


class CommunityCard(BaseModel):
    cover_kind: str | None = None
    cover_ref: str | None = None
    community_id: str
    name: str
    timezone: str
    status: CommunityStatus
    joined: bool
