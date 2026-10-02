import sqlite3
from datetime import datetime

from echo_commons.modules.characters.templates.catalog import MemoryPreloadResource
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.shared.actors import ActorKind, ActorRef


class MemoryBootstrap:
    def __init__(
        self,
        entries: MemoryEntryRepository,
        indexer: MemoryIndexing,
        communities: CommunityRepository,
    ) -> None:
        self.entries, self.indexer, self.communities = entries, indexer, communities

    def seed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        resource: MemoryPreloadResource | None,
        now: datetime,
    ) -> None:
        if resource is None:
            return
        for memory in resource.memories:
            if memory.subject_kind == "self" and memory.subject_id == "self":
                subject = ActorRef(ActorKind.CHARACTER, character_id)
            else:
                subject = ActorRef(ActorKind(memory.subject_kind), memory.subject_id)
                self.communities.require_member(connection, community_id, subject)
            self.entries.preload(
                connection, community_id, character_id, resource, memory, now, subject
            )
        self.indexer.memories(connection, community_id, character_id, now)
