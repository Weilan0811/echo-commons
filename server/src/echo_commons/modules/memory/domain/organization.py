import unicodedata
from dataclasses import dataclass


def normalize_alias(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


@dataclass(frozen=True, slots=True)
class MemoryEntryDraft:
    memory_kind: str
    content: str
    subject_kind: str
    subject_id: str
    visibility: str
    confidence: float
    salience: float


@dataclass(frozen=True, slots=True)
class MemoryEntityDraft:
    local_id: str
    entity_kind: str
    canonical_name: str


@dataclass(frozen=True, slots=True)
class MemoryEdgeDraft:
    from_local_id: str
    to_local_id: str
    edge_kind: str
    confidence: float
