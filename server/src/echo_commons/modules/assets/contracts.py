from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_commons.modules.assets.domain import GenerationPurpose, Purpose


class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropRequest(AssetInput):
    player_id: str = Field(min_length=1)
    client_request_id: str = Field(min_length=1, max_length=120)
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    size: int = Field(gt=0, strict=True)


class SceneContext(AssetInput):
    preset_key: str | None = Field(default=None, max_length=120)
    time_of_day: str = Field(default="", max_length=500)
    lighting: str = Field(default="", max_length=1000)
    palette: str = Field(default="", max_length=1000)
    background_description: str = Field(default="", max_length=4000)


class GenerationRequest(AssetInput):
    player_id: str = Field(min_length=1)
    client_request_id: str = Field(min_length=1, max_length=120)
    purpose: GenerationPurpose
    style_id: str = Field(min_length=1)
    scene_context: SceneContext = Field(default_factory=SceneContext)
    description: str = Field(default="", max_length=8000)
    appearance: str = Field(default="", max_length=4000)
    draft_id: str | None = None
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def materials(self):
        if (self.draft_id is None) != (self.revision is None):
            raise ValueError("draft_id and revision must be provided together")
        if self.draft_id and self.purpose != "character_illustration":
            raise ValueError("Draft materials are only used for character illustrations")
        if not self.draft_id and not self.description.strip():
            raise ValueError("A description or character draft is required")
        return self


class ImageFile(BaseModel):
    variant: str
    width: int
    height: int
    byte_size: int
    mime: Literal["image/webp"] = "image/webp"
    url: str


class AssetView(BaseModel):
    asset_id: str
    owner_player_id: str
    purpose: Purpose
    source: Literal["upload", "generated", "derived"]
    source_asset_id: str | None
    crop: dict[str, int] | None
    created_at_utc: datetime
    images: list[ImageFile]


class GenerationView(BaseModel):
    generation_id: str
    owner_player_id: str
    purpose: GenerationPurpose
    status: Literal["queued", "submitting", "generating", "saving", "completed", "failed"]
    asset_id: str | None
    error_code: str | None
    created_at_utc: datetime
    updated_at_utc: datetime


class StyleView(BaseModel):
    style_id: str
    name: str
    description: str
    purposes: list[GenerationPurpose]
