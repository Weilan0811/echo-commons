from pydantic import BaseModel, ConfigDict, Field


class OutputContractRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str = Field(min_length=1)
    version: str = Field(min_length=1)

    @property
    def schema_id(self) -> str:
        return f"{self.kind}.{self.version}"


class ContextInputRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_id: str = Field(min_length=1)
    snapshot_schema_version: int = Field(default=1, ge=1)
