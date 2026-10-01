from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

from echo_commons.infrastructure.observability.logging import get_logger, log_event
from echo_commons.runtime.modules import ObservabilityModule

logger = get_logger("runtime")


class TraceDeliveryService:
    def __init__(self, runtime: ObservabilityModule) -> None:
        self.runtime = runtime

    async def enqueue_event(
        self, correlation_id: UUID, kind: str, entity_type: str, entity_id: str, payload: dict
    ) -> None:
        """Best-effort enqueue for events outside a core state transaction.

        Agent lifecycle and late-result events must not turn an otherwise
        recoverable task outcome into a worker failure.  The enqueue itself is
        still durable when it succeeds, and the stable trace ID makes the
        bounded retry safe if the first transaction fails after opening.
        """

        trace_id = uuid4()
        for enqueue_attempt in range(1, 3):
            try:
                async with self.runtime.database.transaction() as connection:
                    await self.runtime.agent_traces.enqueue(
                        trace_id=trace_id,
                        correlation_id=correlation_id,
                        kind=kind,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        payload=payload,
                        created_at=self.runtime.clock(),
                        connection=connection,
                    )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "trace.enqueue_failed",
                    correlation_id=correlation_id,
                    worker_id=self.runtime.worker_id,
                    attempt_count=enqueue_attempt,
                    error_code=self.runtime._error_code(exc),
                    error_type=exc.__class__.__name__,
                )
        log_event(
            logger,
            logging.ERROR,
            "trace.enqueue_dropped",
            correlation_id=correlation_id,
            worker_id=self.runtime.worker_id,
            attempt_count=2,
            error_code="trace_enqueue_exhausted",
        )

    async def flush_trace_outbox(
        self,
        *,
        max_items: int | None = None,
        worker_id: str | None = None,
    ) -> int:
        """Materialize a bounded batch of durable Trace outbox entries.

        Delivery failures are released back to the durable queue with a
        bounded retry schedule.  They are intentionally isolated from core
        conversation work: a failed diagnostic write must not change Task or
        Message state.
        """

        await self.runtime.ensure_started()
        batch_size = max_items if max_items is not None else self.runtime.settings.trace_batch_size
        if batch_size < 1:
            raise ValueError("max_items must be positive")
        owner = worker_id or self.runtime.worker_id
        delivered = 0
        for _ in range(batch_size):
            try:
                entry = await self.runtime.traces.claim_next(
                    worker_id=owner,
                    now_utc=self.runtime.clock(),
                    lease_seconds=self.runtime.settings.trace_lease_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "trace.claim_failed",
                    worker_id=owner,
                    error_code=self.runtime._error_code(exc),
                    error_type=exc.__class__.__name__,
                )
                break
            if entry is None:
                break

            try:
                materialized = await self.runtime.traces.materialize(
                    entry.trace_id,
                    worker_id=owner,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error_code = self.runtime._error_code(exc)
                try:
                    exhausted = await self.runtime.traces.retry(
                        entry.trace_id,
                        worker_id=owner,
                        now_utc=self.runtime.clock(),
                        retry_delay=self._trace_retry_delay(entry.attempt_count),
                        max_attempts=max(1, self.runtime.settings.trace_max_attempts),
                        error_code=error_code,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as retry_exc:
                    log_event(
                        logger,
                        logging.ERROR,
                        "trace.retry_persistence_failed",
                        correlation_id=entry.correlation_id,
                        worker_id=owner,
                        attempt_count=entry.attempt_count,
                        error_code=self.runtime._error_code(retry_exc),
                        error_type=retry_exc.__class__.__name__,
                    )
                    break
                log_event(
                    logger,
                    logging.ERROR if exhausted else logging.WARNING,
                    "trace.delivery_exhausted" if exhausted else "trace.delivery_failed",
                    correlation_id=entry.correlation_id,
                    worker_id=owner,
                    attempt_count=entry.attempt_count,
                    error_code=error_code,
                    error_type=exc.__class__.__name__,
                )
                break

            if materialized:
                delivered += 1

        if delivered:
            log_event(
                logger,
                logging.DEBUG,
                "trace.outbox_flushed",
                worker_id=owner,
                batch_size=delivered,
            )
        return delivered

    def _trace_retry_delay(self, attempt_count: int) -> float:
        """Return a bounded exponential delay for one failed delivery."""

        base = max(0.0, self.runtime.settings.trace_retry_backoff_seconds)
        exponent = min(max(attempt_count - 1, 0), 5)
        return min(60.0, base * (2**exponent))


__all__ = ["TraceDeliveryService"]
