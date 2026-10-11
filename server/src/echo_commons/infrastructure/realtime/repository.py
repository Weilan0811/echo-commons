import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.shared.realtime import EventKind, EventReference, EventSource

BATCH_SIZE = 100
RETENTION = timedelta(hours=24)


class EventRepository:
    def append(self, connection: sqlite3.Connection, events: Iterable[EventReference]) -> None:
        at = utc_text(datetime.now(UTC))
        connection.executemany(
            "INSERT INTO realtime_events "
            "(community_id,kind,object_id,source_kind,source_id,audience_json,created_at_utc) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                (
                    e.community_id,
                    e.kind,
                    e.object_id,
                    e.source,
                    e.source_id,
                    json.dumps(e.audience),
                    at,
                )
                for e in events
            ),
        )

    def bounds(self, connection: sqlite3.Connection) -> tuple[int, int]:
        high = connection.execute(
            "SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='realtime_events'),0)"
        ).fetchone()[0]
        floor = connection.execute(
            "SELECT cleaned_through FROM realtime_event_state WHERE singleton=1"
        ).fetchone()[0]
        return floor, high

    def read(self, connection: sqlite3.Connection, community_id: str, after: int):
        return tuple(
            connection.execute(
                "SELECT * FROM realtime_events WHERE community_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (community_id, after, BATCH_SIZE),
            )
        )

    @staticmethod
    def reference(row: sqlite3.Row) -> EventReference:
        return EventReference(
            EventKind(row["kind"]),
            row["community_id"],
            row["object_id"],
            EventSource(row["source_kind"]),
            row["source_id"],
            tuple(json.loads(row["audience_json"])),
        )

    def clean(self, connection: sqlite3.Connection, now: datetime) -> int:
        through = connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM realtime_events WHERE created_at_utc<?",
            (utc_text(now - RETENTION),),
        ).fetchone()[0]
        # 清理完整前缀，使恢复边界始终只有一个定义。
        connection.execute("DELETE FROM realtime_events WHERE sequence<=?", (through,))
        connection.execute(
            "UPDATE realtime_event_state SET cleaned_through=MAX(cleaned_through,?) "
            "WHERE singleton=1",
            (through,),
        )
        return through
