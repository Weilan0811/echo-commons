from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ParticipationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["remote_rules", "remote_willingness", "local_willingness"] = "remote_rules"
    remote_entry_id: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    temperature: float = Field(default=0.1, gt=0)
