from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrganizationEvidence:
    kind: str
    source_id: str
    version: str


@dataclass(frozen=True, slots=True)
class MemoryEntryDraft:
    memory_kind: str
    content: str
    visibility: str
    confidence: float
    salience: float
    sources: tuple[OrganizationEvidence, ...]
