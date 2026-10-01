"""Shared immutable references used by internal Agent contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OutputContractRef(BaseModel):
    """Provider-neutral identifier for the output contract selected by Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)

    @property
    def schema_id(self) -> str:
        return f"{self.kind}.{self.version}"

    @classmethod
    def from_schema_id(cls, schema_id: str) -> OutputContractRef:
        normalized = schema_id.strip()
        kind, separator, version = normalized.rpartition(".")
        if not separator or not kind or not version:
            raise ValueError("output contract must use the 'kind.version' form")
        return cls(kind=kind, version=version)


class ContextInputRef(BaseModel):
    """Identity and content fingerprint of immutable input projected into a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=200)
    snapshot_schema_version: int = Field(default=1, ge=1)
    snapshot_fingerprint: str = Field(min_length=1, max_length=200)


__all__ = ["ContextInputRef", "OutputContractRef"]
