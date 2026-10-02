from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_commons.agents.contracts.refs import OutputContractRef


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActorScope(InputModel):
    community_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)


class ActionSpace(InputModel):
    output_contracts: tuple[OutputContractRef, ...]
    tools: tuple[str, ...] = ()


class SourceVersion(InputModel):
    kind: str
    source_id: str
    version: str


class ToolReadPolicy(InputModel):
    observed_at_utc: datetime
    conversation_id: str | None = None
    upper_sequence: int | None = Field(default=None, ge=0)
    source_versions: tuple[SourceVersion, ...] = ()

    @model_validator(mode="after")
    def paired_conversation_bound(self):
        if (self.conversation_id is None) != (self.upper_sequence is None):
            raise ValueError("conversation and sequence bound must be supplied together")
        return self


class InvocationInput(InputModel, ABC):
    schema_version: Literal[1] = 1
    snapshot_id: str = Field(min_length=1)
    prepared_at_utc: datetime
    scope: ActorScope
    action_space: ActionSpace
    source_versions: tuple[SourceVersion, ...]

    @property
    @abstractmethod
    def read_policy(self) -> ToolReadPolicy:
        pass
