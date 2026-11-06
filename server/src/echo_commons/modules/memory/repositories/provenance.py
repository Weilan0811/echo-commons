from __future__ import annotations

import json
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.memory.domain.summaries import SummaryBatch, SummaryReference
from echo_commons.shared.errors import ConflictError, NotFoundError


class MemoryProvenanceRepository:
    def __init__(self, activities=None):
        self.activities = activities

    def eligible_segments(
        self,
        connection,
        community,
        character,
        visible_ids,
        before,
        *,
        observed_before=None,
        require_readable_thoughts=False,
    ):
        observed_before = observed_before or before
        result = []
        for row in connection.execute(
            "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
            "AND sealed_at_utc<=? ORDER BY position",
            (community, character, utc_text(before)),
        ):
            messages = {
                r[0]
                for r in connection.execute(
                    "SELECT source_id FROM memory_segment_sources WHERE segment_id=? "
                    "AND source_kind='message'",
                    (row["segment_id"],),
                )
            }
            sources = tuple(
                connection.execute(
                    "SELECT * FROM memory_segment_sources WHERE segment_id=?", (row["segment_id"],)
                )
            )
            valid = bool(sources) and messages <= visible_ids
            for source in sources:
                if source["source_kind"] == "game_event":
                    if self.activities is None:
                        valid = False
                        break
                    try:
                        event = self.activities.event(
                            connection, community, character, source["source_id"], observed_before
                        )
                    except NotFoundError:
                        valid = False
                        break
                    valid = valid and event.version == source["source_version"]
                elif source["source_kind"] == "thought":
                    thought = connection.execute(
                        "SELECT * FROM thoughts WHERE character_id=? AND thought_id=?",
                        (character, source["source_id"]),
                    ).fetchone()
                    # 已完成摘要独立保留；读取原文的消费者仍要求 Thought 正文可读。
                    valid = valid and thought is not None
                    if thought is not None:
                        valid = valid and (
                            thought["content"] is not None
                            or (row["status"] == "ingested" and not require_readable_thoughts)
                        )
                        valid = valid and thought["created_at_utc"] <= utc_text(observed_before)
            if valid:
                result.append(row)
        return tuple(result)

    def context_summaries(
        self, connection, community, character, eligible, covered, before, *, limit=8
    ):
        return tuple(
            row
            for row in reversed(eligible)
            if row["segment_id"] not in covered
            and row["status"] == "ingested"
            and row["summary_text"]
            and row["ingested_at_utc"] <= utc_text(before)
        )[:limit]

    def digest_segments(self, connection, digest_id):
        return frozenset(
            row[0]
            for row in connection.execute(
                "SELECT segment_id FROM memory_digest_segments WHERE digest_id=?",
                (digest_id,),
            )
        )

    def latest_digests(
        self, connection, community, character, *, recorded_before, eligible_segment_ids
    ):
        rows = tuple(
            connection.execute(
                "SELECT d.* FROM memory_digests d JOIN memory_summary_batches b USING(batch_id) "
                "WHERE b.community_id=? AND b.character_id=? AND d.created_at_utc<=? "
                "ORDER BY d.created_at_utc DESC,d.digest_id",
                (community, character, utc_text(recorded_before)),
            )
        )
        result, represented = [], set()
        for row in rows:
            covered = self.digest_segments(connection, row["digest_id"])
            if covered and covered <= eligible_segment_ids and not covered <= represented:
                result.append(row)
                represented.update(covered)
        return tuple(reversed(result))

    def digest_for_batch(self, connection, batch):
        return connection.execute(
            "SELECT * FROM memory_digests WHERE batch_id=?",
            (batch.batch_id,),
        ).fetchone()

    def add_digest(self, connection, batch, content, now):
        identity = str(uuid4())
        connection.execute(
            "INSERT INTO memory_digests VALUES (?,?,?,?,?)",
            (identity, batch.batch_id, content, "1", utc_text(now)),
        )
        inherited = {}
        for previous in batch.previous_digest_ids:
            for row in connection.execute(
                "SELECT segment_id,summary_version FROM memory_digest_segments WHERE digest_id=?",
                (previous,),
            ):
                inherited[row[0]] = row[1]
        inherited.update((ref.segment_id, ref.version) for ref in batch.sources)
        connection.executemany(
            "INSERT INTO memory_digest_segments VALUES (?,?,?)",
            [(identity, key, version) for key, version in inherited.items()],
        )
        self.consume_continuity(connection, batch.sources, now, digest_id=identity)
        return identity

    def consume_continuity(self, connection, references, now, *, digest_id=None):
        connection.executemany(
            "INSERT INTO memory_continuity_consumption VALUES (?,?,?) "
            "ON CONFLICT(segment_id) DO NOTHING",
            [(ref.segment_id, digest_id, utc_text(now)) for ref in references],
        )

    def continuity_consumed(self, connection, segment_id):
        return (
            connection.execute(
                "SELECT 1 FROM memory_continuity_consumption WHERE segment_id=?",
                (segment_id,),
            ).fetchone()
            is not None
        )

    def organization_consumed(self, connection, segment_id, version):
        return (
            connection.execute(
                "SELECT 1 FROM memory_organization_consumption WHERE segment_id=? AND "
                "summary_version=?",
                (segment_id, version),
            ).fetchone()
            is not None
        )

    def get_batch(self, connection, community_id, character_id, batch_id):
        row = connection.execute(
            "SELECT * FROM memory_summary_batches WHERE community_id=? AND character_id=? "
            "AND batch_id=?",
            (community_id, character_id, batch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Summary batch does not exist in the character scope")
        return SummaryBatch(
            batch_id,
            community_id,
            character_id,
            tuple(
                SummaryReference(r[0], r[1])
                for r in connection.execute(
                    "SELECT segment_id,summary_version FROM memory_summary_batch_items "
                    "WHERE batch_id=? ORDER BY ordinal",
                    (batch_id,),
                )
            ),
            row["source_version"],
            tuple(
                r[0]
                for r in connection.execute(
                    "SELECT digest_id FROM memory_summary_batch_digests WHERE batch_id=? "
                    "ORDER BY ordinal",
                    (batch_id,),
                )
            ),
            utc_datetime(row["created_at_utc"]),
        )

    def batch_summaries(self, connection, batch):
        rows = []
        for ref in batch.sources:
            row = connection.execute(
                "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
                "AND segment_id=?",
                (batch.community_id, batch.character_id, ref.segment_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "ingested"
                or (row["summary_version"] or "") != ref.version
            ):
                raise ConflictError("Frozen summary batch source is unavailable")
            rows.append(row)
        return tuple(rows)

    def create_batch(
        self,
        connection,
        community,
        character,
        summaries,
        previous,
        now,
        *,
        consumer,
        organization_sources=None,
    ):
        if not summaries:
            raise ValueError("Summary batch requires actual segments")
        if any(
            row["community_id"] != community
            or row["character_id"] != character
            or row["status"] != "ingested"
            for row in summaries
        ):
            raise ConflictError("Summary batch requires ingested sources from its own scope")
        version = json.dumps(
            {
                "consumer": consumer.value,
                "previous_digests": [
                    (row["digest_id"], row["content_version"]) for row in previous
                ],
                "summaries": [
                    (row["segment_id"], row["summary_version"] or "") for row in summaries
                ],
                "organization_sources": organization_sources,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        existing = connection.execute(
            "SELECT batch_id FROM memory_summary_batches WHERE character_id=? AND source_version=?",
            (character, version),
        ).fetchone()
        if existing:
            return self.get_batch(connection, community, character, existing[0])
        identity = str(uuid4())
        connection.execute(
            "INSERT INTO memory_summary_batches(batch_id,community_id,character_id,"
            "source_version,created_at_utc,organization_sources_json) VALUES (?,?,?,?,?,?)",
            (
                identity,
                community,
                character,
                version,
                utc_text(now),
                json.dumps(organization_sources) if organization_sources is not None else None,
            ),
        )
        connection.executemany(
            "INSERT INTO memory_summary_batch_items VALUES (?,?,?,?)",
            [
                (identity, ordinal, row["segment_id"], row["summary_version"] or "")
                for ordinal, row in enumerate(summaries)
            ],
        )
        connection.executemany(
            "INSERT INTO memory_summary_batch_digests VALUES (?,?,?)",
            [(identity, row["digest_id"], ordinal) for ordinal, row in enumerate(previous)],
        )
        return self.get_batch(connection, community, character, identity)

    def get_digest(self, connection, community, character, digest_id):
        row = connection.execute(
            "SELECT d.* FROM memory_digests d JOIN memory_summary_batches b USING(batch_id) "
            "WHERE b.community_id=? AND b.character_id=? AND d.digest_id=?",
            (community, character, digest_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Character digest does not exist in this scope")
        return row

    def progress(self, connection, community, character):
        row = connection.execute(
            "SELECT item.value FROM memory_change_batches b "
            "JOIN memory_core_refreshes progress USING(batch_id),json_each(b.materials_json) item "
            "WHERE b.community_id=? AND b.character_id=? "
            "AND progress.outcome IN ('completed','no_op') "
            "AND json_extract(item.value,'$.fact_kind')='core_memory_request' "
            "ORDER BY b.created_at_utc DESC,b.batch_id DESC LIMIT 1",
            (community, character),
        ).fetchone()
        if row is None:
            return None
        request = json.loads(json.loads(row[0])["content"])
        return request if request["unread_memory_ids"] else None

    def record_sources(self, connection, community, character, record_kind, memory_id, version):
        table = {"fact": "memory_facts", "cognition": "memory_cognitions"}[record_kind]
        record = connection.execute(
            f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
            f"AND memory_id=? AND version=?",
            (community, character, memory_id, version),
        ).fetchone()
        if record is None:
            raise NotFoundError("Long-term record does not exist in this character scope")
        found = []
        source_table = {"fact": "memory_fact_sources", "cognition": "memory_cognition_sources"}[
            record_kind
        ]
        for reference in connection.execute(
            f"SELECT * FROM {source_table} WHERE memory_id=? AND version=? "
            "ORDER BY source_kind,source_id,source_version",
            (memory_id, version),
        ):
            if reference["source_kind"] == "message":
                row = connection.execute(
                    "SELECT text content,'1' version FROM messages WHERE "
                    "community_id=? AND message_id=?",
                    (community, reference["source_id"]),
                ).fetchone()
            elif reference["source_kind"] == "thought":
                row = connection.execute(
                    "SELECT content,content_version version FROM thoughts WHERE community_id=? "
                    "AND character_id=? AND thought_id=?",
                    (community, character, reference["source_id"]),
                ).fetchone()
            elif reference["source_kind"] == "game_event":
                from datetime import UTC, datetime

                try:
                    event = (
                        self.activities.event(
                            connection,
                            community,
                            character,
                            reference["source_id"],
                            datetime.now(UTC),
                        )
                        if self.activities
                        else None
                    )
                    row = {"content": event.content, "version": event.version} if event else None
                except NotFoundError:
                    row = None
            else:
                row = connection.execute(
                    "SELECT c.content,m.question,m.blueprint_version version "
                    "FROM memory_author_chunks c "
                    "JOIN memory_author_materials m USING(material_id) "
                    "JOIN character_instances i USING(character_id) WHERE i.community_id=? "
                    "AND m.character_id=? AND c.chunk_id=?",
                    (community, character, reference["source_id"]),
                ).fetchone()
                if row is not None and row["question"]:
                    row = {
                        "content": f"问题：{row['question']}\n回答：{row['content']}",
                        "version": row["version"],
                    }
            readable = bool(
                row is not None and row["version"] == reference["source_version"] and row["content"]
            )
            found.append(
                dict(
                    source_kind=reference["source_kind"],
                    source_id=reference["source_id"],
                    source_version=reference["source_version"],
                    readable=readable,
                    content=row["content"] if readable else None,
                )
            )
        if record_kind == "cognition":
            for support in connection.execute(
                "SELECT s.*,f.content,f.status FROM memory_cognition_fact_supports s "
                "JOIN memory_facts f ON f.memory_id=s.fact_id AND f.version=s.fact_version "
                "WHERE s.memory_id=? AND s.version=? AND f.community_id=? AND f.character_id=?",
                (memory_id, version, community, character),
            ):
                original = self.record_sources(
                    connection,
                    community,
                    character,
                    "fact",
                    support["fact_id"],
                    support["fact_version"],
                )
                readable = (
                    support["status"] in ("current", "superseded")
                    and bool(original)
                    and all(item["readable"] for item in original)
                )
                found.append(
                    dict(
                        source_kind="memory_fact",
                        source_id=support["fact_id"],
                        source_version=str(support["fact_version"]),
                        readable=readable,
                        content=support["content"] if readable else None,
                    )
                )
        return found

    def view(self, connection, community, character, view_kind):
        return connection.execute(
            "SELECT * FROM memory_views WHERE community_id=? AND character_id=? AND view_kind=?",
            (community, character, view_kind),
        ).fetchone()
