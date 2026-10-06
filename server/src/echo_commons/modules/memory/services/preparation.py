import asyncio
import logging
from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.materials import MemoryMaterials

logger = logging.getLogger("echo_commons.memory.preparation")


class MemoryPreparation:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = InitializationRepository()
        self.materials = MemoryMaterials(SearchRepository())

    async def run_once(self) -> bool:
        return await asyncio.to_thread(self.prepare_materials)

    def prepare_materials(self) -> bool:
        with self.database.read() as connection:
            rows = self.repository.pending(connection, "materials")
        for row in rows:
            if row["phase"] != "materials":
                continue
            now = datetime.now(UTC)
            try:
                with self.database.transaction() as connection:
                    self.materials.authors(
                        connection, row["community_id"], row["character_id"], now
                    )
                    self.repository.advance(
                        connection,
                        row["character_id"],
                        "completed" if row["memory_mode"] == "simple" else "organize",
                        now,
                    )
            except Exception:
                logger.exception(
                    "Author materials preparation failed: character=%s", row["character_id"]
                )
                with self.database.transaction() as connection:
                    self.repository.fail(
                        connection, row["character_id"], "material_preparation_failed", now
                    )
            return True
        return False
