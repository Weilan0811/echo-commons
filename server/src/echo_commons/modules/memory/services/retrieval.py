from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.tokenization import fts_match_query
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


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


class MemoryRetrieval:
    def __init__(
        self,
        instances: InstanceReader,
        conversations: ConversationRepository,
        entries: MemoryEntryRepository,
        perspective: PerspectiveReader,
        search: SearchRepository,
    ) -> None:
        (
            self.instances,
            self.conversations,
            self.entries,
            self.perspective,
            self.search_repository,
        ) = instances, conversations, entries, perspective, search

    def sources(
        self, connection: sqlite3.Connection, scope: SearchScope
    ) -> dict[tuple[str, str], SearchHit]:
        self.instances.get(connection, scope.community_id, scope.character_id)
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
            hit = SearchHit(
                "memory_entry", row["memory_id"], row["content_version"], row["content"], None
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
            for message in self.perspective.messages(connection, observation):
                if message.created_at_utc <= scope.observed_at_utc:
                    hit = SearchHit(
                        "message", message.message_id, "1", message.text, message.conversation_id
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
        if not 1 <= limit <= 50:
            raise ValueError("Search result limit must be between 1 and 50")
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
        return tuple(hits)


def _source_version(sources: dict[tuple[str, str], SearchHit]) -> str:
    return json.dumps(
        sorted((kind, identity, hit.source_version) for (kind, identity), hit in sources.items()),
        separators=(",", ":"),
    )
