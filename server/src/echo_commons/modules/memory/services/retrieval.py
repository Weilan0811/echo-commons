from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.policy import RetrievalPolicy
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.tokenization import fts_match_query
from echo_commons.modules.memory.services.vectors import MemoryVectors
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError

logger = logging.getLogger("echo_commons.memory.retrieval")


@dataclass(frozen=True, slots=True)
class SearchScope:
    community_id: str
    character_id: str
    observed_at_utc: datetime
    conversation_id: str | None = None
    upper_sequence: int | None = None

    def __post_init__(self) -> None:
        if (self.conversation_id is None) != (self.upper_sequence is None):
            raise ValueError("Frozen conversation search requires its sequence boundary")
        if self.upper_sequence is not None and self.upper_sequence < 0:
            raise ValueError("Search sequence must be nonnegative")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("Search time must include timezone")


@dataclass(frozen=True, slots=True)
class SearchHit:
    source_kind: str
    source_id: str
    source_version: str
    text: str
    conversation_id: str | None
    memory_kind: str | None = None
    occurred_at_utc: datetime | None = None


class MemoryRetrieval:
    def __init__(
        self,
        instances: InstanceReader,
        conversations: ConversationRepository,
        entries: MemoryEntryRepository,
        perspective: PerspectiveReader,
        search: SearchRepository,
        vectors: MemoryVectors | None = None,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        (
            self.instances,
            self.conversations,
            self.entries,
            self.perspective,
            self.search_repository,
        ) = instances, conversations, entries, perspective, search
        self.vectors = vectors
        self.policy = policy or RetrievalPolicy()

    async def search_async(
        self,
        database: Database,
        scope: SearchScope,
        query: str,
        *,
        limit: int = 5,
        expected_source_version: str | None = None,
    ) -> tuple[SearchHit, ...]:
        def read():
            with database.read() as connection:
                return self.search(
                    connection,
                    scope,
                    query,
                    limit=self.policy.candidate_limit,
                    expected_source_version=expected_source_version,
                )

        fulltext = await asyncio.to_thread(read)
        if self.vectors is None:
            return fulltext[:limit]
        vector = None
        try:
            vector = (await self.vectors.gateway.embed((query,)))[0]
        except (ModelGatewayError, ModelConfigurationError, TimeoutError) as error:
            logger.warning("Semantic search unavailable: %s", getattr(error, "code", "timeout"))

        def merge():
            with database.read() as connection:
                sources = self.sources(connection, scope)
                if (
                    expected_source_version is not None
                    and _source_version(sources) != expected_source_version
                ):
                    raise ConflictError("memory_source_changed")
                semantic = (
                    self.vectors.ranked(
                        connection,
                        scope.community_id,
                        scope.character_id,
                        vector,
                        limit=self.policy.candidate_limit,
                    )
                    if vector is not None
                    else ()
                )
                scores = {}
                for ranking in (
                    [(hit.source_kind, hit.source_id, hit.source_version) for hit in fulltext],
                    semantic,
                ):
                    for rank, (kind, identity, version) in enumerate(ranking, 1):
                        key = (kind, identity)
                        if key in sources and sources[key].source_version == version:
                            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                hits, seen = [], set()
                for key in sorted(scores, key=lambda key: (-scores[key], key)):
                    hit = sources[key]
                    if hit.text in seen:
                        continue
                    hits.append(hit)
                    seen.add(hit.text)
                    if len(hits) == limit:
                        break
                return tuple(hits)

        return await asyncio.to_thread(merge)

    def sources(
        self, connection: sqlite3.Connection, scope: SearchScope
    ) -> dict[tuple[str, str], SearchHit]:
        instance = self.instances.get(connection, scope.community_id, scope.character_id)
        if scope.conversation_id is not None:
            self.perspective.messages(
                connection,
                ObservationScope(
                    scope.community_id,
                    scope.conversation_id,
                    ActorRef("character", scope.character_id),
                    0,
                ),
            )
        found = {}
        for row in self.entries.active_rows(
            connection,
            scope.community_id,
            scope.character_id,
            valid_at=datetime.now(UTC),
            recorded_before=scope.observed_at_utc,
        ):
            if (
                instance.memory_mode is MemoryMode.SIMPLE
                and row["source_kind"] != "blueprint_preload"
            ):
                continue
            hit = SearchHit(
                "memory_entry",
                row["memory_id"],
                row["content_version"],
                row["content"],
                None,
                row["memory_kind"],
            )
            found[(hit.source_kind, hit.source_id)] = hit
        for row in connection.execute(
            "SELECT c.*,m.blueprint_version,m.material_kind,m.question FROM memory_author_chunks c "
            "JOIN memory_author_materials m ON m.material_id=c.material_id "
            "WHERE m.character_id=? AND m.created_at_utc<=?",
            (scope.character_id, utc_text(scope.observed_at_utc)),
        ):
            text = (row["question"] + "\n" if row["question"] else "") + row["content"]
            hit = SearchHit(
                "author_chunk",
                row["chunk_id"],
                row["blueprint_version"],
                text,
                None,
                row["material_kind"],
            )
            found[(hit.source_kind, hit.source_id)] = hit
        for conversation in self.conversations.for_actor(
            connection, scope.community_id, ActorRef("character", scope.character_id)
        ):
            upper = (
                scope.upper_sequence
                if conversation.conversation_id == scope.conversation_id
                else conversation.next_sequence - 1
            )
            observation = ObservationScope(
                scope.community_id,
                conversation.conversation_id,
                ActorRef("character", scope.character_id),
                upper,
            )
            visible_messages = {}
            for message in self.perspective.messages(connection, observation):
                if message.created_at_utc <= scope.observed_at_utc:
                    visible_messages[message.message_id] = message
                    if instance.memory_mode is MemoryMode.SIMPLE:
                        continue
                    hit = SearchHit(
                        "message",
                        message.message_id,
                        "1",
                        message.text,
                        message.conversation_id,
                        occurred_at_utc=message.created_at_utc,
                    )
                    found[(hit.source_kind, hit.source_id)] = hit
            for row in connection.execute(
                "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
                "AND conversation_id=? AND status='ingested' AND summary_text IS NOT NULL "
                "AND ingested_at_utc<=? AND last_message_sequence<=?",
                (
                    scope.community_id,
                    scope.character_id,
                    conversation.conversation_id,
                    utc_text(scope.observed_at_utc),
                    upper,
                ),
            ):
                source_ids = {
                    item[0]
                    for item in connection.execute(
                        "SELECT source_id FROM memory_segment_sources WHERE segment_id=? "
                        "AND source_kind='message'",
                        (row["segment_id"],),
                    )
                }
                if not source_ids or not source_ids <= visible_messages.keys():
                    continue
                hit = SearchHit(
                    "segment_summary",
                    row["segment_id"],
                    row["summary_version"],
                    row["summary_text"],
                    row["conversation_id"],
                    occurred_at_utc=utc_datetime(row["ingested_at_utc"]),
                )
                found[(hit.source_kind, hit.source_id)] = hit
        return found

    def source_version(self, connection: sqlite3.Connection, scope: SearchScope) -> str:
        sources = self.sources(connection, scope)
        return _source_version(sources)

    def search(
        self,
        connection: sqlite3.Connection,
        scope: SearchScope,
        query: str,
        *,
        limit: int = 5,
        expected_source_version: str | None = None,
    ) -> tuple[SearchHit, ...]:
        if not 1 <= limit <= max(50, self.policy.candidate_limit):
            raise ValueError("Search result limit exceeds candidate budget")
        sources = self.sources(connection, scope)
        actual_version = _source_version(sources)
        if expected_source_version is not None and actual_version != expected_source_version:
            raise ConflictError("memory_source_changed")
        match = fts_match_query(query)
        if match is None:
            return ()
        hits = []
        for row in self.search_repository.candidates(
            connection, scope.community_id, scope.character_id, match
        ):
            source = sources.get((row["source_kind"], row["source_id"]))
            if source is not None and source.source_version == row["source_version"]:
                hits.append(source)
                if len(hits) == limit:
                    break
        return tuple(hits[:limit])


def _source_version(sources: dict[tuple[str, str], SearchHit]) -> str:
    return json.dumps(
        sorted((kind, identity, hit.source_version) for (kind, identity), hit in sources.items()),
        separators=(",", ":"),
    )
