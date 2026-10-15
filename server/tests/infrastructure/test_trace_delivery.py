import sqlite3
from datetime import UTC, datetime

import pytest
from support.messages import build_system

from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.observability.outbox import claim_traces, deliver_trace, fail_trace
from echo_commons.infrastructure.observability.trace_delivery import TraceDelivery
from echo_commons.modules.conversations.domain.message import PlayerMessage


def trace_system(tmp_path):
    system = build_system(tmp_path)
    system.intake.send(
        "community", "conversation", PlayerMessage("alice", "trace", "消息仍然可以读取")
    )
    delivery = TraceDelivery(
        system.database, batch_size=25, lease_seconds=30, max_attempts=2, retry_backoff_seconds=0
    )
    return system, delivery


def test_real_readonly_failure_records_retry_and_keeps_message(tmp_path):
    system, delivery = trace_system(tmp_path)
    with system.database.transaction() as connection:
        claimed = claim_traces(connection, delivery.owner, datetime.now(UTC), 30, 2, 25)
    assert len(claimed) == 1
    with pytest.raises(StorageError) as failure, system.database.transaction() as connection:
        connection.execute("PRAGMA query_only = ON")
        deliver_trace(connection, claimed[0], delivery.owner, datetime.now(UTC))
    assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
    assert failure.value.code == "sqlite_readonly"
    with system.database.transaction() as connection:
        fail_trace(
            connection, claimed[0], delivery.owner, datetime.now(UTC), failure.value.code, 2, 0
        )
    with system.database.read() as connection:
        row = connection.execute("SELECT * FROM trace_outbox").fetchone()
        assert row["status"] == "pending" and row["last_error_code"] == "sqlite_readonly"
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    assert delivery.deliver_once() == 1
    assert delivery.deliver_once() == 0
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM trace_outbox").fetchone()[0] == 0


def test_repeated_real_storage_failure_becomes_explicit_failed_trace(tmp_path):
    system, delivery = trace_system(tmp_path)
    for attempt in (1, 2):
        with system.database.transaction() as connection:
            claimed = claim_traces(connection, delivery.owner, datetime.now(UTC), 30, 2, 25)
        with pytest.raises(StorageError) as failure, system.database.transaction() as connection:
            connection.execute("PRAGMA query_only = ON")
            deliver_trace(connection, claimed[0], delivery.owner, datetime.now(UTC))
        with system.database.transaction() as connection:
            fail_trace(
                connection, claimed[0], delivery.owner, datetime.now(UTC), failure.value.code, 2, 0
            )
            row = connection.execute("SELECT * FROM trace_outbox").fetchone()
            assert row["attempt_count"] == attempt
    assert row["status"] == "failed"
    assert delivery.deliver_once() == 0
