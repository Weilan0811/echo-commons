import asyncio
import logging
from datetime import UTC, datetime

from echo_commons.modules.memory.repositories.author_batches import AuthorBatchRepository
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.reflection.contexts.authors import author_snapshot
from echo_commons.shared.errors import BusinessError

logger = logging.getLogger("echo_commons.memory.initialization")


class FullMemoryInitialization:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.database = coordinator.database
        self.initializations = InitializationRepository()
        self.authors = AuthorBatchRepository()

    async def run_once(self):
        return await asyncio.to_thread(self.advance)

    def advance(self):
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            rows = self.initializations.pending(connection, "organize")
            if not rows:
                return False
            row = rows[0]
            character, community = row["character_id"], row["community_id"]
            if row["organization_run_id"]:
                run = self.coordinator.runs.get(
                    connection, community, character, row["organization_run_id"]
                )
                if run.status == "failed":
                    if not row["attempts"]:
                        self.initializations.fail(
                            connection, character, "author_organization_failed", now
                        )
                        return True
                    connection.execute(
                        "UPDATE memory_initializations SET attempts=attempts-1 "
                        "WHERE character_id=?",
                        (character,),
                    )
                    resumed = self.coordinator._resume(connection, run, now)
                    if resumed.status == "failed":
                        snapshot = self.coordinator.runs.snapshot(
                            connection, community, character, str(run.graph_run_id)
                        )
                        resumed = self.coordinator.start_snapshot_in(connection, snapshot, now)
                        connection.execute(
                            "UPDATE memory_initializations SET organization_run_id=? "
                            "WHERE character_id=?",
                            (str(resumed.graph_run_id), character),
                        )
                    return True
                if run.status not in ("completed",):
                    if run.status in ("partial", "cancelled"):
                        self.initializations.fail(
                            connection, character, "author_organization_failed", now
                        )
                        return True
                    return False
            connection.execute("SAVEPOINT author_preparation")
            try:
                policy = self.coordinator.context.graph.policy
                batch = self.authors.freeze(
                    connection,
                    community,
                    character,
                    now,
                    max_count=policy.max_materials,
                    max_chars=policy.max_material_chars,
                )
                if batch is None:
                    connection.execute("RELEASE SAVEPOINT author_preparation")
                    self.initializations.advance(connection, character, "views", now)
                    return True
                snapshot = author_snapshot(
                    self.coordinator.context.graph, self.authors, connection, batch, now
                )
                run = self.coordinator.start_snapshot_in(connection, snapshot, now)
                connection.execute(
                    "UPDATE memory_initializations SET organization_run_id=?,attempts=0,"
                    "updated_at_utc=? WHERE character_id=?",
                    (str(run.graph_run_id), now.isoformat(), character),
                )
            except (ValueError, BusinessError):
                connection.execute("ROLLBACK TO SAVEPOINT author_preparation")
                connection.execute("RELEASE SAVEPOINT author_preparation")
                logger.exception("Author source preparation failed")
                self.initializations.fail(
                    connection, character, "author_material_budget_exceeded", now
                )
                return True
            connection.execute("RELEASE SAVEPOINT author_preparation")
            return True
