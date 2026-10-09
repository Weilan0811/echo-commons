import asyncio
import logging
import sqlite3
from datetime import UTC, datetime

import numpy as np

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.embeddings import EmbeddingGateway
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError
from echo_commons.modules.memory.repositories.vectors import VectorRepository

logger = logging.getLogger("echo_commons.memory.vectors")


class MemoryVectors:
    def __init__(self, database: Database, gateway: EmbeddingGateway) -> None:
        self.database, self.gateway = database, gateway
        self.repository = VectorRepository()
        self.active_document_ids: frozenset[int] = frozenset()

    def _pending(self, identity: str) -> tuple[dict, ...]:
        with self.database.read() as connection:
            rows = self.repository.pending(connection, identity, self.gateway.policy)
            self.active_document_ids = frozenset(row["document_id"] for row in rows)
            return rows

    def _save(self, rows: tuple[dict, ...], vectors: tuple[np.ndarray, ...], identity: str) -> None:
        with self.database.transaction() as connection:
            for row, vector in zip(rows, vectors, strict=True):
                self.repository.save(connection, row, vector, identity, datetime.now(UTC))

    def _failure(self, rows: tuple[dict, ...], identity: str, error: Exception) -> None:
        code = getattr(
            error, "code", "embedding_text_budget" if isinstance(error, ValueError) else "timeout"
        )
        with self.database.transaction() as connection:
            for row in rows:
                self.repository.failure(
                    connection,
                    row,
                    identity,
                    code,
                    getattr(error, "provider_attempt", 0),
                    datetime.now(UTC),
                )

    async def run_once(self) -> bool:
        try:
            return await self._run_once()
        finally:
            self.active_document_ids = frozenset()

    async def _run_once(self) -> bool:
        identity = self.gateway.identity
        rows = await asyncio.to_thread(self._pending, identity)
        if not rows:
            return False
        try:
            vectors = await self.gateway.embed(
                tuple(row["display_text"] for row in rows), background=True
            )
        except (ModelGatewayError, ModelConfigurationError, TimeoutError, ValueError) as error:
            await asyncio.to_thread(self._failure, rows, identity, error)
            logger.warning(
                "Vector backfill failed: code=%s, materials=%s",
                getattr(error, "code", "timeout"),
                len(rows),
            )
            return False
        await asyncio.to_thread(self._save, rows, vectors, identity)
        return True

    def ranked(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        query: np.ndarray,
        *,
        limit: int,
    ) -> tuple[tuple[str, str, str], ...]:
        rows = self.repository.candidates(
            connection, community_id, character_id, self.gateway.identity, len(query)
        )
        if not rows:
            return ()
        matrix = np.stack([np.frombuffer(row["vector"], dtype=np.float32) for row in rows])
        scores = (matrix @ query) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))
        return tuple(
            (rows[index]["source_kind"], rows[index]["source_id"], rows[index]["source_version"])
            for index in np.argsort(-scores)[:limit]
            if scores[index] > 0
        )
