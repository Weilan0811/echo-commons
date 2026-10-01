from datetime import datetime

import aiosqlite

from echo_commons.domain.memory import MemoryView, MemoryViewKind
from echo_commons.domain.memory_sources import content_version
from echo_commons.store.memory_provenance import rows
from echo_commons.store.repository_support import utc_text


async def view_source_version(
    view: MemoryView, *, now_utc: datetime, connection: aiosqlite.Connection
) -> str | None:
    if view.view_kind is MemoryViewKind.STATE_SUMMARY:
        states = await rows(
            connection,
            """SELECT e.state_kind,e.state_version,e.value,
            (e.expires_at_utc IS NULL OR e.expires_at_utc>?) AS active
            FROM character_state_entries e WHERE e.character_id=? AND e.state_version=(
              SELECT MAX(n.state_version) FROM character_state_entries n
              WHERE n.character_id=e.character_id AND n.state_kind=e.state_kind)
            ORDER BY e.state_kind""",
            (utc_text(now_utc), view.character_id),
        )
        if not states or not any(r["active"] for r in states):
            return None
        return content_version([tuple(r) for r in states])
    versions = []
    for ref in view.source_refs:
        found = await rows(
            connection,
            """SELECT memory_id,content_version,content FROM memory_entries
            WHERE account_id=? AND character_id=? AND memory_id=?
            AND visibility IN ('resident','recallable') AND invalidated_at_utc IS NULL
            AND (expires_at_utc IS NULL OR expires_at_utc>?)""",
            (view.account_id, view.character_id, ref.removeprefix("memory:"), utc_text(now_utc)),
        )
        if not found:
            return None
        versions.append(tuple(found[0]))
    return content_version(versions)
