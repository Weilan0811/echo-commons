import sqlite3
from datetime import datetime

from echo_commons.modules.characters.templates.catalog import MemoryPreloadResource
from echo_commons.modules.memory.domain.authored import AuthorMaterial
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.memory.services.materials import MemoryMaterials


class MemoryBootstrap:
    def prepare(
        self,
        connection: sqlite3.Connection,
        character_id: str,
        blueprint_id: str,
        blueprint_version: str,
        materials: tuple[AuthorMaterial, ...],
        now: datetime,
    ) -> None:
        InitializationRepository().register(
            connection, character_id, blueprint_id, blueprint_version, materials, now
        )

    def retry(self, connection: sqlite3.Connection, character_id: str, now: datetime) -> None:
        InitializationRepository().retry(connection, character_id, now)

    def __init__(
        self,
        indexer: MemoryIndexing,
    ) -> None:
        self.indexer = indexer

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
            InitializationRepository().preload(
                connection, community_id, character_id, resource, memory, now
            )
        MemoryMaterials(self.indexer.search).authors(connection, community_id, character_id, now)
