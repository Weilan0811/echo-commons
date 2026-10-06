from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryViewDraft:
    kind: str
    content: str
    source_refs: tuple[str, ...]
