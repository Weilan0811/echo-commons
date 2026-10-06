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
    graph_entity_limit: int = Field(default=3, ge=1)
    graph_edge_limit: int = Field(default=16, ge=1)
    candidate_limit: int = Field(default=100, ge=1)


class MemoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vector: VectorPolicy = Field(default_factory=VectorPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
