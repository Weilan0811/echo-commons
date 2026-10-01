from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.observability.outbox import claim_traces, deliver_trace, fail_trace


class TraceDelivery:
    def __init__(
        self,
        database: Database,
        *,
        batch_size: int,
        lease_seconds: float,
        max_attempts: int,
        retry_backoff_seconds: float,
    ) -> None:
        self.database, self.batch_size, self.lease_seconds = database, batch_size, lease_seconds
        self.max_attempts, self.retry_backoff_seconds = max_attempts, retry_backoff_seconds
        self.owner = str(uuid4())

    def deliver_once(self) -> int:
        with self.database.transaction() as connection:
            claimed = claim_traces(
                connection,
                self.owner,
                datetime.now(UTC),
                self.lease_seconds,
                self.max_attempts,
                self.batch_size,
            )
        delivered = 0
        for trace_id in claimed:
            try:
                with self.database.transaction() as connection:
                    delivered += deliver_trace(connection, trace_id, self.owner, datetime.now(UTC))
            except StorageError as error:
                with self.database.transaction() as connection:
                    fail_trace(
                        connection,
                        trace_id,
                        self.owner,
                        datetime.now(UTC),
                        error.code,
                        self.max_attempts,
                        self.retry_backoff_seconds,
                    )
        return delivered
