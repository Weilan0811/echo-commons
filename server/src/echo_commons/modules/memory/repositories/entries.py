from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.templates.catalog import AuthoredMemory, MemoryPreloadResource
from echo_commons.shared.actors import ActorRef


class MemoryEntryRepository:
    def preload(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        resource: MemoryPreloadResource,
        memory: AuthoredMemory,
        now: datetime,
        subject: ActorRef,
    ) -> None:
        # 模板中的自身引用在创建实例时解析，记忆身份属于实例。
        connection.execute(
            "INSERT INTO memory_entries "
            "(memory_id, community_id, character_id, memory_kind, content, "
            "confidence, salience, source_kind, source_ref, "
            "subject_kind, subject_id, visibility, content_version, recorded_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                community_id,
                character_id,
                memory.memory_kind,
                memory.content,
                memory.confidence,
                memory.salience,
                "blueprint_preload",
                f"{resource.resource_id}/{memory.memory_id}@{resource.content_version}",
                subject.kind.value,
                subject.actor_id,
                memory.visibility,
                resource.content_version,
                utc_text(now),
            ),
        )
