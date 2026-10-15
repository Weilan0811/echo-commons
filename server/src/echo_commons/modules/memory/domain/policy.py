from pydantic import BaseModel, ConfigDict, Field


class VectorPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    profile: str = "embedding"
    dimensions: int = Field(default=1536, ge=1)
    batch_size: int = Field(default=16, ge=1, le=128)
    batch_max_chars: int = Field(default=16000, ge=1)
    timeout_seconds: float = Field(default=30, gt=0)


class RetrievalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    automatic_limit: int = Field(default=5, ge=1, le=50)
    automatic_max_chars: int = Field(default=4000, ge=1)
    input_max_chars: int = Field(default=32000, ge=1)
    candidate_limit: int = Field(default=100, ge=1)


class CyclePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scan_seconds: float = Field(default=30, gt=0)
    experience_idle_seconds: float = Field(default=600, gt=0)
    summary_target_chars: int = Field(default=12000, ge=1)
    summary_wait_seconds: float = Field(default=7200, gt=0)


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vector: VectorPolicy = Field(default_factory=VectorPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    cycles: CyclePolicy = Field(default_factory=CyclePolicy)
