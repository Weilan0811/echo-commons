from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["apimart", "dashscope", "minimax"]
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    credential_ref: str = Field(min_length=1)


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    count: int = Field(default=1, ge=1, le=1)
    reference_images: tuple[str, ...] = ()


class ImageSubmission(BaseModel):
    task_id: str | None = None
    urls: tuple[str, ...] = ()
    usage: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def result_source(self):
        if bool(self.task_id) == bool(self.urls):
            raise ValueError("Image submission requires either a remote task or image URLs")
        return self


class ImageTask(BaseModel):
    status: Literal["pending", "processing", "completed", "failed", "cancelled"]
    urls: tuple[str, ...] = ()
