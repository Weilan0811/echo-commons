from datetime import datetime
from uuid import uuid4

import aiosqlite

from echo_commons.domain.errors import DomainInvariantError
from echo_commons.domain.memory import MemorySegment
from echo_commons.domain.memory_sources import (
    MemorySourceKind,
    MemorySourceRef,
    SummaryBatch,
    content_version,
)
from echo_commons.domain.messages import Message
from echo_commons.store.repository_support import require_write_connection, utc_text


async def rows(
    connection: aiosqlite.Connection, sql: str, args: tuple[object, ...] = ()
) -> list[aiosqlite.Row]:
    async with connection.execute(sql, args) as cursor:
        return await cursor.fetchall()


class MemoryProvenanceRepository:
    async def get_batch(
        self,
        batch_id: str,
        *,
        account_id: str,
        character_id: str,
        connection: aiosqlite.Connection,
    ) -> SummaryBatch | None:
        """Reload frozen provenance after restart without selecting a newer window."""
        found = await rows(
            connection,
            "SELECT * FROM memory_summary_batches WHERE batch_id=? "
            "AND account_id=? AND character_id=?",
            (batch_id, account_id, character_id),
        )
        if not found:
            return None
        header = found[0]
        items = await rows(
            connection,
            "SELECT * FROM memory_summary_batch_items WHERE batch_id=? ORDER BY ordinal",
            (batch_id,),
        )
        return SummaryBatch(
            batch_id,
            account_id,
            header["conversation_id"],
            character_id,
            tuple(
                MemorySourceRef(
                    MemorySourceKind.SEGMENT_SUMMARY, r["segment_id"], r["summary_version"]
                )
                for r in items
            ),
            header["source_version"],
            header["previous_digest_id"],
        )

    async def complete_reply_prefix(
        self, messages: tuple[Message, ...], *, connection: aiosqlite.Connection
    ) -> tuple[Message, ...]:
        """Retreat before a reply group if the requested bound cuts its bubbles."""
        for result_id in dict.fromkeys(m.result_id for m in messages if m.result_id):
            group = await rows(
                connection,
                "SELECT MIN(message_sequence),MAX(message_sequence) FROM messages "
                "WHERE result_id=?",
                (str(result_id),),
            )
            if group[0][0] < messages[0].message_sequence:
                raise DomainInvariantError("existing_segment_splits_reply")
            if group[0][1] > messages[-1].message_sequence:
                return tuple(m for m in messages if m.message_sequence < group[0][0])
        return messages

    async def bind_segment_thoughts(
        self, segment: MemorySegment, *, connection: aiosqlite.Connection
    ) -> None:
        require_write_connection(connection)
        await connection.execute(
            """UPDATE thoughts SET segment_id=?
            WHERE account_id=? AND conversation_id=? AND character_id=? AND segment_id IS NULL
            AND result_id IN (SELECT result_id FROM messages WHERE account_id=?
                AND conversation_id=? AND message_sequence BETWEEN ? AND ?)""",
            (
                str(segment.segment_id),
                segment.account_id,
                segment.conversation_id,
                segment.character_id,
                segment.account_id,
                segment.conversation_id,
                segment.first_message_sequence,
                segment.last_message_sequence,
            ),
        )
        sources = await self.segment_sources(str(segment.segment_id), connection=connection)
        version = content_version([(r.kind.value, r.source_id, r.version) for r in sources])
        await connection.execute(
            "UPDATE memory_segments SET source_version=? WHERE segment_id=?",
            (version, str(segment.segment_id)),
        )

    async def segment_sources(
        self, segment_id: str, *, connection: aiosqlite.Connection
    ) -> tuple[MemorySourceRef, ...]:
        messages = await rows(
            connection,
            """SELECT m.message_id FROM messages m
            JOIN memory_segments s ON s.account_id=m.account_id
              AND s.conversation_id=m.conversation_id
            WHERE s.segment_id=? AND m.message_sequence BETWEEN
              s.first_message_sequence AND s.last_message_sequence
            ORDER BY m.message_sequence""",
            (segment_id,),
        )
        thoughts = await rows(
            connection,
            "SELECT thought_id,content_version FROM thoughts "
            "WHERE segment_id=? ORDER BY thought_id",
            (segment_id,),
        )
        return tuple(
            [MemorySourceRef(MemorySourceKind.MESSAGE, r[0], r[0]) for r in messages]
            + [MemorySourceRef(MemorySourceKind.THOUGHT, r[0], r[1]) for r in thoughts]
        )

    async def record_coverage(
        self,
        owner_kind: str,
        owner_id: str,
        sources: tuple[MemorySourceRef, ...],
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        require_write_connection(connection)
        existing = await rows(
            connection,
            "SELECT source_kind,source_id,source_version "
            "FROM memory_source_coverage WHERE owner_kind=? AND owner_id=?",
            (owner_kind, owner_id),
        )
        if existing:
            if {tuple(r) for r in existing} != {
                (s.kind.value, s.source_id, s.version) for s in sources
            }:
                raise DomainInvariantError("coverage_replay_mismatch")
            return
        if len({(s.kind, s.source_id) for s in sources}) != len(sources):
            raise DomainInvariantError("duplicate_coverage_source")
        if owner_kind == "segment_summary":
            expected = await self.segment_sources(owner_id, connection=connection)
            if not expected or set(expected) != set(sources):
                raise DomainInvariantError("summary_coverage_mismatch")
        elif owner_kind == "diary":
            diary = await rows(
                connection, "SELECT * FROM diary_entries WHERE diary_id=?", (owner_id,)
            )
            if not diary:
                raise DomainInvariantError("diary_coverage_owner_missing")
            for source in sources:
                found = await rows(
                    connection,
                    """SELECT 1 FROM thoughts WHERE thought_id=?
                    AND content_version=? AND account_id=? AND character_id=? AND game_day=?""",
                    (
                        source.source_id,
                        source.version,
                        diary[0]["account_id"],
                        diary[0]["character_id"],
                        diary[0]["game_day"],
                    ),
                )
                if source.kind is not MemorySourceKind.THOUGHT or not found:
                    raise DomainInvariantError("diary_coverage_source_mismatch")
        else:
            raise DomainInvariantError("unknown_coverage_owner")
        for source in sources:
            await connection.execute(
                """INSERT INTO memory_source_coverage
                (owner_kind,owner_id,source_kind,source_id,source_version) VALUES (?,?,?,?,?)""",
                (owner_kind, owner_id, source.kind.value, source.source_id, source.version),
            )

    async def cleanup_thoughts(self, *, connection: aiosqlite.Connection) -> int:
        """Unsealed/unfinished segment consumers retain their original private input."""
        require_write_connection(connection)
        async with connection.execute("""DELETE FROM thoughts AS t
            WHERE EXISTS (SELECT 1 FROM memory_source_coverage c
                WHERE c.owner_kind='diary' AND c.source_kind='thought'
                AND c.source_id=t.thought_id AND c.source_version=t.content_version)
            AND EXISTS (SELECT 1 FROM memory_segments s JOIN memory_source_coverage c
                ON c.owner_id=s.segment_id AND c.owner_kind='segment_summary'
                WHERE s.segment_id=t.segment_id AND s.status='ingested'
                AND s.summary_version IS NOT NULL AND c.source_kind='thought'
                AND c.source_id=t.thought_id AND c.source_version=t.content_version)""") as cursor:
            return cursor.rowcount

    async def latest_digest(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        through_sequence: int,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        found = await rows(
            connection,
            """SELECT d.* FROM conversation_digests d
            JOIN memory_summary_batches b ON b.batch_id=d.batch_id
            WHERE b.account_id=? AND b.conversation_id=? AND b.character_id=?
              AND d.covers_through_sequence<=?
            ORDER BY d.covers_through_sequence DESC LIMIT 1""",
            (account_id, conversation_id, character_id, through_sequence),
        )
        return found[0] if found else None

    async def get_digest(
        self,
        digest_id: str,
        *,
        account_id: str,
        conversation_id: str,
        character_id: str,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        found = await rows(
            connection,
            """SELECT d.* FROM conversation_digests d
            JOIN memory_summary_batches b ON b.batch_id=d.batch_id
            WHERE d.digest_id=? AND b.account_id=? AND b.conversation_id=?
              AND b.character_id=?""",
            (digest_id, account_id, conversation_id, character_id),
        )
        return found[0] if found else None

    async def list_context_summaries(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        after_sequence: int,
        through_sequence: int,
        connection: aiosqlite.Connection,
    ) -> list[aiosqlite.Row]:
        return await rows(
            connection,
            """SELECT * FROM memory_segments
            WHERE account_id=? AND conversation_id=? AND character_id=? AND status='ingested'
            AND summary_version IS NOT NULL AND last_message_sequence>? AND last_message_sequence<=?
            ORDER BY first_message_sequence DESC LIMIT 8""",
            (account_id, conversation_id, character_id, after_sequence, through_sequence),
        )

    async def freeze_batch(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        through_sequence: int,
        now_utc: datetime,
        connection: aiosqlite.Connection,
        limit: int = 16,
        consumer: str = "continuity_compress",
        max_material_chars: int | None = None,
    ) -> SummaryBatch | None:
        require_write_connection(connection)
        if limit < 1:
            raise DomainInvariantError("summary_batch_limit_must_be_positive")
        if max_material_chars is not None and max_material_chars < 1:
            raise DomainInvariantError("summary_batch_material_budget_must_be_positive")
        previous = await self.latest_digest(
            account_id,
            conversation_id,
            character_id,
            through_sequence=through_sequence,
            connection=connection,
        )
        if consumer not in ("continuity_compress", "memory_organize"):
            raise DomainInvariantError("unknown_summary_consumer")
        after = (
            previous["covers_through_sequence"]
            if previous and consumer == "continuity_compress"
            else 0
        )
        material_chars = (
            len(previous["content"].strip())
            if previous is not None and max_material_chars is not None
            else 0
        )
        segments = await rows(
            connection,
            """SELECT * FROM memory_segments
            WHERE account_id=? AND conversation_id=? AND character_id=?
            AND last_message_sequence>? AND last_message_sequence<=?
            ORDER BY first_message_sequence""",
            (account_id, conversation_id, character_id, after, through_sequence),
        )
        selected = []
        cursor = after
        for segment in segments:
            if consumer == "memory_organize":
                consumed = await rows(
                    connection,
                    "SELECT 1 FROM memory_organization_consumption "
                    "WHERE segment_id=? AND summary_version=?",
                    (segment["segment_id"], segment["summary_version"]),
                )
                if consumed:
                    cursor = segment["last_message_sequence"]
                    continue
            # Sequence numbers are global; only missing messages in THIS conversation are gaps.
            gap = await rows(
                connection,
                """SELECT 1 FROM messages WHERE account_id=?
                AND conversation_id=? AND message_sequence>? AND message_sequence<? LIMIT 1""",
                (account_id, conversation_id, cursor, segment["first_message_sequence"]),
            )
            if gap or segment["status"] != "ingested" or not segment["summary_version"]:
                break
            if max_material_chars is not None:
                summary_chars = len(segment["summary_text"].strip())
                if material_chars + summary_chars > max_material_chars:
                    break
            selected.append(segment)
            cursor = segment["last_message_sequence"]
            material_chars += (
                len(segment["summary_text"].strip()) if max_material_chars is not None else 0
            )
            if len(selected) >= limit:
                break
        if not selected:
            return None
        refs = tuple(
            MemorySourceRef(MemorySourceKind.SEGMENT_SUMMARY, s["segment_id"], s["summary_version"])
            for s in selected
        )
        previous_id = previous["digest_id"] if previous else None
        version = content_version((previous_id, [(r.source_id, r.version) for r in refs]))
        existing = await rows(
            connection,
            "SELECT batch_id FROM memory_summary_batches "
            "WHERE account_id=? AND conversation_id=? AND character_id=? AND source_version=?",
            (account_id, conversation_id, character_id, version),
        )
        if existing:
            return await self.get_batch(
                existing[0]["batch_id"],
                account_id=account_id,
                character_id=character_id,
                connection=connection,
            )
        batch = SummaryBatch(
            str(uuid4()), account_id, conversation_id, character_id, refs, version, previous_id
        )
        await connection.execute(
            "INSERT INTO memory_summary_batches VALUES (?,?,?,?,?,?,?)",
            (
                batch.batch_id,
                account_id,
                conversation_id,
                character_id,
                version,
                previous_id,
                utc_text(now_utc),
            ),
        )
        await connection.executemany(
            "INSERT INTO memory_summary_batch_items VALUES (?,?,?,?)",
            [(batch.batch_id, i, r.source_id, r.version) for i, r in enumerate(refs)],
        )
        return batch

    async def validate_batch(
        self, batch: SummaryBatch, *, connection: aiosqlite.Connection
    ) -> list[aiosqlite.Row]:
        header = await rows(
            connection, "SELECT * FROM memory_summary_batches WHERE batch_id=?", (batch.batch_id,)
        )
        if not header or tuple(
            header[0][k]
            for k in (
                "account_id",
                "conversation_id",
                "character_id",
                "source_version",
                "previous_digest_id",
            )
        ) != (
            batch.account_id,
            batch.conversation_id,
            batch.character_id,
            batch.source_version,
            batch.previous_digest_id,
        ):
            raise DomainInvariantError("summary_batch_mismatch")
        items = await rows(
            connection,
            """SELECT s.*,i.summary_version AS frozen_version
            FROM memory_summary_batch_items i JOIN memory_segments s ON s.segment_id=i.segment_id
            WHERE i.batch_id=? ORDER BY i.ordinal""",
            (batch.batch_id,),
        )
        if tuple((s["segment_id"], s["frozen_version"]) for s in items) != tuple(
            (r.source_id, r.version) for r in batch.sources
        ) or any(
            s["summary_version"] != s["frozen_version"] or s["status"] != "ingested" for s in items
        ):
            raise DomainInvariantError("summary_source_changed")
        return items

    async def commit_digest(
        self,
        batch: SummaryBatch,
        content: str,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> str:
        require_write_connection(connection)
        if not content.strip() or len(content.strip()) > 8000:
            raise DomainInvariantError("digest_content_outside_budget")
        items = await self.validate_batch(batch, connection=connection)
        existing = await rows(
            connection, "SELECT * FROM conversation_digests WHERE batch_id=?", (batch.batch_id,)
        )
        if existing:
            if existing[0]["content"] != content.strip():
                raise DomainInvariantError("digest_replay_mismatch")
            return existing[0]["digest_id"]
        current = await self.latest_digest(
            batch.account_id,
            batch.conversation_id,
            batch.character_id,
            through_sequence=2**63 - 1,
            connection=connection,
        )
        if (current["digest_id"] if current else None) != batch.previous_digest_id:
            raise DomainInvariantError("digest_progress_changed")
        if current and items[0]["first_message_sequence"] <= current["covers_through_sequence"]:
            raise DomainInvariantError("digest_coverage_overlap")
        identity = str(uuid4())
        await connection.execute(
            "INSERT INTO conversation_digests VALUES (?,?,?,?,?,?,?)",
            (
                identity,
                batch.batch_id,
                batch.previous_digest_id,
                content.strip(),
                content_version(content.strip()),
                items[-1]["last_message_sequence"],
                utc_text(now_utc),
            ),
        )
        return identity

    async def commit_organization(
        self,
        batch: SummaryBatch,
        *,
        outcome: str,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        """Call after reviewed memory writes in the same transaction, including no-op."""
        require_write_connection(connection)
        await self.validate_batch(batch, connection=connection)
        if outcome not in ("completed", "no_op"):
            raise DomainInvariantError("invalid_organization_outcome")
        for ref in batch.sources:
            consumed = await rows(
                connection,
                "SELECT batch_id,outcome FROM memory_organization_consumption "
                "WHERE segment_id=? AND summary_version=?",
                (ref.source_id, ref.version),
            )
            if consumed and (consumed[0]["batch_id"], consumed[0]["outcome"]) != (
                batch.batch_id,
                outcome,
            ):
                raise DomainInvariantError("organization_progress_changed")
        for ref in batch.sources:
            await connection.execute(
                """INSERT INTO memory_organization_consumption
                VALUES (?,?,?,?,?) ON CONFLICT(segment_id,summary_version) DO NOTHING""",
                (ref.source_id, ref.version, batch.batch_id, outcome, utc_text(now_utc)),
            )
