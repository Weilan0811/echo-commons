from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING

from echo_commons import __version__
from echo_commons.infrastructure.observability.logging import get_logger, log_event
from echo_commons.runtime.common import duration_ms as _duration_ms
from echo_commons.runtime.errors import DatabaseUnavailableError
from echo_commons.store.memory_search_repositories import MemorySearchUnavailableError
from echo_commons.store.migrations import migrate

logger = get_logger("runtime")

if TYPE_CHECKING:
    from echo_commons.runtime.application_runtime import ApplicationRuntime


class RuntimeLifecycle:
    def __init__(self, runtime: ApplicationRuntime) -> None:
        self.runtime = runtime

    async def start(self) -> None:
        if self.runtime.started:
            return
        started_at = perf_counter()
        try:
            self.runtime.accepting_work = True
            await migrate(self.runtime.database)
            async with self.runtime.database.transaction(immediate=True) as connection:
                await self.runtime.runtime_conversations.ensure(
                    account_id=self.runtime.settings.account_id,
                    conversation_id=self.runtime.settings.default_conversation_id,
                    now_utc=self.runtime.clock(),
                    connection=connection,
                )
                await self.runtime.memory_initialization.ensure_account_preload(
                    self.runtime.settings.account_id,
                    now_utc=self.runtime.clock(),
                    connection=connection,
                )
                try:
                    character_ids = self.runtime.identity_catalog.character_ids
                    for character_id in character_ids:
                        await self.runtime.memory_search.rebuild_scope(
                            self.runtime.settings.account_id,
                            character_id,
                            connection=connection,
                        )
                except MemorySearchUnavailableError:
                    # Sparse retrieval has a structured SQL fallback.  A
                    # missing FTS5 build must not prevent the Runtime startup.
                    log_event(
                        logger,
                        logging.WARNING,
                        "memory_search.fts_unavailable",
                    )
                await self.runtime.runtime_tasks.recover_expired(
                    self.runtime.clock(), connection=connection
                )
                await self.runtime.reflection_graph_nodes.recover_expired(
                    self.runtime.clock(), connection=connection
                )
                await self.runtime.traces.recover_expired(
                    self.runtime.clock(), connection=connection
                )
                await self.runtime.meta.set(
                    "last_successful_start_version", __version__, connection
                )
            self.runtime.started = True
        except Exception as exc:
            await self.runtime.database.close()
            log_event(
                logger,
                logging.ERROR,
                "runtime.start_failed",
                error_code=self.runtime._error_code(exc),
                error_type=exc.__class__.__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise DatabaseUnavailableError("database startup failed") from exc
        log_event(
            logger,
            logging.INFO,
            "runtime.started",
            duration_ms=_duration_ms(started_at),
        )

    async def stop(self) -> None:
        self.runtime.accepting_work = False
        self.runtime.started = False
        await self.runtime.database.close()
        log_event(logger, logging.INFO, "runtime.stopped")

    async def ensure_started(self) -> None:
        if not self.runtime.started:
            await self.start()


__all__ = ["RuntimeLifecycle"]
