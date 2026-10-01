"""Initialize character memory from versioned author content."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from echo_server.domain.memory import MemoryEntry
from echo_server.services.identity import IdentityCatalog
from echo_server.store.memory_repositories import MemoryEntryRepository


class MemoryInitializationService:
    """Project stable character preloads into an account's memory namespace."""

    def __init__(
        self,
        memory_entries: MemoryEntryRepository,
        identity_catalog: IdentityCatalog,
    ) -> None:
        self.memory_entries = memory_entries
        self.identity_catalog = identity_catalog

    async def ensure_account_preload(
        self,
        account_id: str,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> int:
        """Ensure each registered character's authored pages exist for an account.

        The resource date is used as the stable recorded timestamp so restarting
        the Runtime never changes a page's identity or resident ordering.
        """

        inserted_or_existing = 0
        for character_id in self.identity_catalog.character_ids:
            character = self.identity_catalog.character(character_id)
            preload = character.memory_preload
            if preload is None:
                continue
            try:
                recorded_at = datetime.fromisoformat(preload.updated_at).replace(tzinfo=UTC)
            except ValueError:
                recorded_at = now_utc.astimezone(UTC)
            for authored in preload.memories:
                entry = MemoryEntry(
                    account_id=account_id,
                    character_id=character_id,
                    memory_id=authored.memory_id,
                    memory_kind=authored.memory_kind,
                    content=authored.content,
                    confidence=authored.confidence,
                    salience=authored.salience,
                    source_kind="authored_preload",
                    source_ref=f"{preload.resource_id}:{authored.memory_id}",
                    subject_kind=authored.subject_kind,
                    subject_id=authored.subject_id or character_id,
                    visibility=authored.visibility,
                    content_version=preload.content_version,
                    recorded_at_utc=recorded_at,
                )
                await self.memory_entries.ensure(entry, connection=connection)
                inserted_or_existing += 1
        return inserted_or_existing


__all__ = ["MemoryInitializationService"]
