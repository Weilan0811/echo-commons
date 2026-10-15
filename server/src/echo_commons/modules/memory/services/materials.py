import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.tokenization import tokenized_text


def chunk_ranges(
    content: str, *, max_chars: int = 800, overlap: int = 100
) -> tuple[tuple[int, int], ...]:
    if max_chars < 1 or not 0 <= overlap < max_chars:
        raise ValueError("Chunk overlap must fit within its text budget")
    ranges = []
    start = 0
    while start < len(content):
        end = min(start + max_chars, len(content))
        if end < len(content):
            # 优先保留完整段落；超过预算的段落按正文位置拆分。
            boundary = content.rfind("\n\n", start + max_chars // 2, end)
            if boundary >= 0:
                end = boundary + 2
        if content[start:end].strip():
            ranges.append((start, end))
        if end == len(content):
            break
        start = max(start + 1, end - overlap)
    return tuple(ranges)


class MemoryMaterials:
    def __init__(self, search: SearchRepository) -> None:
        self.search = search

    def authors(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, now: datetime
    ) -> None:
        materials = connection.execute(
            "SELECT * FROM memory_author_materials WHERE character_id=? "
            "ORDER BY material_kind,position",
            (character_id,),
        ).fetchall()
        for material in materials:
            for position, (start, end) in enumerate(chunk_ranges(material["content"])):
                chunk_id = f"{material['material_id']}:chunk:{position}"
                content = material["content"][start:end]
                connection.execute(
                    "INSERT INTO memory_author_chunks VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(material_id,position) DO NOTHING",
                    (chunk_id, material["material_id"], position, start, end, content),
                )
                text = (material["question"] + "\n" if material["question"] else "") + content
                self.search.replace(
                    connection,
                    community_id,
                    character_id,
                    None,
                    "author_chunk",
                    chunk_id,
                    material["blueprint_version"],
                    text,
                    tokenized_text(text),
                    None,
                    now,
                )

    def summaries(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, now: datetime
    ) -> None:
        for row in connection.execute(
            "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
            "AND status='ingested' AND summary_text IS NOT NULL",
            (community_id, character_id),
        ):
            self.search.replace(
                connection,
                community_id,
                character_id,
                None,
                "segment_summary",
                row["segment_id"],
                row["summary_version"],
                row["summary_text"],
                tokenized_text(row["summary_text"]),
                utc_datetime(row["ingested_at_utc"]),
                now,
            )
