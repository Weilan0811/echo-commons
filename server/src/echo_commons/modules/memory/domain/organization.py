from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from echo_commons.shared.actors import ActorRef


class MemoryRecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryRecordRef(MemoryRecordModel):
    record_kind: Literal["fact", "cognition"]
    memory_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class MemoryFactContent(MemoryRecordModel):
    topic: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=6000)
    participants: tuple[ActorRef, ...] = ()
    occurred_at_utc: AwareDatetime | None = None
    conditions: str = Field(default="", max_length=1000)
    salience: float = Field(default=0.5, ge=0, le=1)

    @field_validator("topic", "content")
    @classmethod
    def text_required(cls, value):
        if not value.strip():
            raise ValueError("Memory fact requires meaningful text")
        return value


class MemoryCognitionContent(MemoryRecordModel):
    topic: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=6000)
    applies_to: str = Field(min_length=1, max_length=1000)
    target: ActorRef | None = Field(
        default=None, description="输入提供的实际认识对象；背景人物只写自然称呼。"
    )
    salience: float = Field(default=0.5, ge=0, le=1)

    @field_validator("topic", "content", "applies_to")
    @classmethod
    def text_required(cls, value):
        if not value.strip():
            raise ValueError("Memory cognition requires meaningful text")
        return value


class FactAdd(MemoryRecordModel):
    operation: Literal["add"] = "add"
    local_key: str = Field(min_length=1, max_length=100)
    fact: MemoryFactContent
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class FactSupport(MemoryRecordModel):
    operation: Literal["support"] = "support"
    local_key: str = Field(min_length=1, max_length=100)
    previous: MemoryRecordRef
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class FactCorrect(MemoryRecordModel):
    operation: Literal["correct"] = "correct"
    local_key: str = Field(min_length=1, max_length=100)
    previous: MemoryRecordRef
    fact: MemoryFactContent
    evidence_refs: tuple[str, ...] = Field(min_length=1)


FactOperation: TypeAlias = Annotated[
    FactAdd | FactSupport | FactCorrect, Field(discriminator="operation")
]


class FactCandidateRef(MemoryRecordModel):
    kind: Literal["candidate"] = "candidate"
    local_key: str = Field(min_length=1, max_length=100)


class SavedFactRef(MemoryRecordRef):
    record_kind: Literal["fact"] = "fact"
    kind: Literal["saved"] = "saved"


FactSupportRef: TypeAlias = Annotated[FactCandidateRef | SavedFactRef, Field(discriminator="kind")]


class CognitionAdd(MemoryRecordModel):
    operation: Literal["add"] = "add"
    cognition: MemoryCognitionContent
    supporting_facts: tuple[FactSupportRef, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class CognitionReplace(MemoryRecordModel):
    operation: Literal["replace"] = "replace"
    previous: MemoryRecordRef
    cognition: MemoryCognitionContent
    supporting_facts: tuple[FactSupportRef, ...] = ()
    evidence_refs: tuple[str, ...] = ()


CognitionOperation: TypeAlias = Annotated[
    CognitionAdd | CognitionReplace, Field(discriminator="operation")
]


class OrganizationEvidence(MemoryRecordModel):
    kind: str
    source_id: str
    version: str
    known_at_utc: datetime | None = None
