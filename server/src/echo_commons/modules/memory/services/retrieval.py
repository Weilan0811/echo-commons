from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.policy import RetrievalPolicy
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.tokenization import fts_match_query
from echo_commons.modules.memory.services.vectors import MemoryVectors
from echo_commons.modules.perspective.contracts import (
    ConversationBoundary,
    ObservationScope,
    PerspectiveReader,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("echo_commons.memory.retrieval")


@dataclass(frozen=True, slots=True)
class SearchScope:
    community_id: str
    character_id: str
    observed_at_utc: datetime
    conversation_id: str | None = None
    upper_sequence: int | None = None
    conversations: tuple[ConversationBoundary, ...] | None = None

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
    occurred_at_utc: datetime | None = None
    context_label: str = ""


class MemoryRetrieval:
    def __init__(
        self,
        instances: InstanceReader,
        conversations: ConversationRepository,
        records: LongTermMemoryRepository,
        perspective: PerspectiveReader,
        search: SearchRepository,
        vectors: MemoryVectors | None = None,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        (
            self.instances,
            self.conversations,
            self.records,
            self.perspective,
            self.search_repository,
        ) = instances, conversations, records, perspective, search
        self.activities = None
        self.vectors = vectors
        self.policy = policy or RetrievalPolicy()

    def select_automatic(
        self, hits: tuple[SearchHit, ...], existing: set[str]
    ) -> tuple[SearchHit, ...]:
        selected, chars, seen = [], 0, set(existing)
        # 搜索已经限制相关性，在匹配候选中优先保留正式事实，顺序相同时沿用检索排名。
        for hit in sorted(hits, key=lambda item: item.source_kind != "memory_fact"):
            if hit.text in seen or chars + len(hit.text) > self.policy.automatic_max_chars:
                continue
            selected.append(hit)
            seen.add(hit.text)
            chars += len(hit.text)
            if len(selected) == self.policy.automatic_limit:
                break
        return tuple(selected)

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
        for row in self.records.active_rows(
            connection,
            scope.community_id,
            scope.character_id,
            recorded_before=scope.observed_at_utc,
        ):
            if instance.memory_mode is MemoryMode.SIMPLE:
                continue
            hit = SearchHit(
                f"memory_{row['record_kind']}",
                row["memory_id"],
                row["content_version"],
                f"记忆类型：{row['record_kind']}\n主题：{row['topic']}\n{row['content']}",
                None,
                utc_datetime(row["occurred_at_utc"]) if row["occurred_at_utc"] else None,
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
            )
            found[(hit.source_kind, hit.source_id)] = hit
        visible_messages = {}
        scenes = scope.conversations
        if scenes is None:
            scenes = tuple(
                ConversationBoundary(
                    conversation_id=conversation.conversation_id,
                    kind=conversation.kind.value,
                    name="私聊" if conversation.kind == "direct" else "群聊",
                    upper_sequence=scope.upper_sequence
                    if conversation.conversation_id == scope.conversation_id
                    else conversation.next_sequence - 1,
                    membership_ids=tuple(
                        member.membership_id
                        for member in self.conversations.members(
                            connection, conversation.conversation_id, current_only=False
                        )
                        if member.actor == ActorRef("character", scope.character_id)
                        and member.joined_at_utc <= scope.observed_at_utc
                    ),
                )
                for conversation in self.conversations.for_actor(
                    connection, scope.community_id, ActorRef("character", scope.character_id)
                )
            )
        for scene in scenes:
            for membership in scene.membership_ids:
                observation = ObservationScope(
                    scope.community_id,
                    scene.conversation_id,
                    ActorRef("character", scope.character_id),
                    scene.upper_sequence,
                    membership,
                )
                for message in self.perspective.messages(connection, observation):
                    if message.created_at_utc > scope.observed_at_utc:
                        continue
                    visible_messages[message.message_id] = message
                    if instance.memory_mode is MemoryMode.SIMPLE:
                        continue
                    hit = SearchHit(
                        "message",
                        message.message_id,
                        "1",
                        message.text,
                        message.conversation_id,
                        message.created_at_utc,
                        scene.name
                        + (
                            "｜私人范围"
                            if scene.kind == "direct" or message.visibility == "recipients"
                            else "｜群内范围"
                        ),
                    )
                    found[(hit.source_kind, hit.source_id)] = hit
        provenance = MemoryProvenanceRepository(self.activities)
        eligible = {
            row["segment_id"]
            for row in provenance.eligible_segments(
                connection,
                scope.community_id,
                scope.character_id,
                frozenset(visible_messages),
                scope.observed_at_utc,
            )
        }
        for row in connection.execute(
            "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
            "AND status='ingested' AND summary_text IS NOT NULL AND ingested_at_utc<=?",
            (scope.community_id, scope.character_id, utc_text(scope.observed_at_utc)),
        ):
            source_ids = {
                item[0]
                for item in connection.execute(
                    "SELECT source_id FROM memory_segment_sources WHERE segment_id=? AND "
                    "source_kind='message'",
                    (row["segment_id"],),
                )
            }
            if row["segment_id"] not in eligible:
                continue
            names = tuple(
                dict.fromkeys(
                    scene.name
                    for scene in scenes
                    if any(
                        visible_messages[identity].conversation_id == scene.conversation_id
                        for identity in source_ids
                    )
                )
            )
            hit = SearchHit(
                "segment_summary",
                row["segment_id"],
                row["summary_version"],
                row["summary_text"],
                None,
                utc_datetime(row["ended_at_utc"]),
                "自身回忆｜" + "、".join(names),
            )
            found[(hit.source_kind, hit.source_id)] = hit
        for digest in provenance.latest_digests(
            connection,
            scope.community_id,
            scope.character_id,
            recorded_before=scope.observed_at_utc,
            eligible_segment_ids=frozenset(eligible),
        ):
            hit = SearchHit(
                "conversation_digest",
                digest["digest_id"],
                digest["content_version"],
                digest["content"],
                None,
                utc_datetime(digest["created_at_utc"]),
                "自身经历摘要",
            )
            found[(hit.source_kind, hit.source_id)] = hit
        for key, hit in tuple(found.items()):
            if hit.source_kind not in ("memory_fact", "memory_cognition"):
                continue
            supports = provenance.record_sources(
                connection,
                scope.community_id,
                scope.character_id,
                hit.source_kind.removeprefix("memory_"),
                hit.source_id,
                int(hit.source_version),
            )
            original = []
            for support in supports:
                if support["source_kind"] == "memory_fact":
                    original.extend(
                        provenance.record_sources(
                            connection,
                            scope.community_id,
                            scope.character_id,
                            "fact",
                            support["source_id"],
                            int(support["source_version"]),
                        )
                    )
                else:
                    original.append(support)
            permitted = all(s["readable"] for s in supports)
            labels = []
            for support in original:
                if support["source_kind"] == "message":
                    permitted = ("message", support["source_id"]) in found
                    if permitted:
                        labels.append(found[("message", support["source_id"])].context_label)
                elif support["source_kind"] == "thought":
                    message = connection.execute(
                        "SELECT m.message_id FROM messages m JOIN thoughts t USING(result_id) "
                        "WHERE t.thought_id=? AND t.character_id=?",
                        (support["source_id"], scope.character_id),
                    ).fetchone()
                    permitted = message is not None and ("message", message[0]) in found
                    if permitted:
                        labels.append(found[("message", message[0])].context_label)
                    elif self.activities is not None:
                        thought = connection.execute(
                            "SELECT * FROM thoughts WHERE thought_id=? AND character_id=?",
                            (support["source_id"], scope.character_id),
                        ).fetchone()
                        permitted = bool(
                            thought
                            and thought["activity_result_id"]
                            and self.activities.thought_visible(
                                connection,
                                scope.community_id,
                                scope.character_id,
                                thought,
                                scope.observed_at_utc,
                            )
                        )
                        if permitted:
                            labels.append("自身游戏内心")
                elif support["source_kind"] == "game_event":
                    permitted = bool(self.activities)
                    if permitted:
                        try:
                            self.activities.event(
                                connection,
                                scope.community_id,
                                scope.character_id,
                                support["source_id"],
                                scope.observed_at_utc,
                            )
                        except NotFoundError:
                            permitted = False
                        else:
                            labels.append("自身游戏经历")
                if not permitted:
                    break
            if not permitted:
                del found[key]
            else:
                found[key] = replace(
                    hit, context_label="自身记忆｜" + "、".join(dict.fromkeys(labels))
                )
        return found

    def source_version(self, connection: sqlite3.Connection, scope: SearchScope) -> str:
        sources = self.sources(connection, scope)
        return _source_version(sources)

    def related_records(self, connection, scope, queries, *, limit=8):
        sources = {
            key: value
            for key, value in self.sources(connection, scope).items()
            if value.source_kind in ("memory_fact", "memory_cognition")
        }
        found = {}
        for query in queries:
            match = fts_match_query(query)
            if match is None:
                continue
            count = 0
            for row in self.search_repository.candidates(
                connection, scope.community_id, scope.character_id, match
            ):
                hit = sources.get((row["source_kind"], row["source_id"]))
                if hit is None or hit.source_version != row["source_version"]:
                    continue
                found.setdefault((hit.source_kind, hit.source_id), hit)
                count += 1
                if count == limit:
                    break
        return tuple(found.values())

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
