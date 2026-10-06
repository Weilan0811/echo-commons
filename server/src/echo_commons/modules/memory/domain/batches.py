from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorBatch:
    batch_id: str
    community_id: str
    character_id: str
    source_version: str
    chunk_ids: tuple[str, ...]
    source_kind: str = "author_material_batch"
