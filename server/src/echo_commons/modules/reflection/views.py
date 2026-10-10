import asyncio
import json

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.reflection.contracts.context import FactMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.modules.reflection.supplements import supplement


class ViewScheduling:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.database = coordinator.database
        self.changes = MemoryChangeRepository()

    async def run_once(self):
        return await asyncio.to_thread(self.scan)

    def scan(self):
        with self.database.transaction() as connection:
            now = utc_now()
            scopes = connection.execute(
                "SELECT i.* FROM character_instances i JOIN communities c USING(community_id) "
                "WHERE i.memory_mode='full' AND c.status='active' AND (i.memory_status='ready' "
                "OR (i.memory_status='preparing' AND EXISTS "
                "(SELECT 1 FROM memory_initializations p "
                "WHERE p.character_id=i.character_id AND p.phase='views'))) ORDER BY i.character_id"
            ).fetchall()
            for scope in scopes:
                community, character = scope["community_id"], scope["character_id"]
                active = connection.execute(
                    "SELECT 1 FROM reflection_graph_runs WHERE community_id=? "
                    "AND character_id=? AND graph_kind='view_refresh' "
                    "AND status IN ('pending','running','retry_wait') LIMIT 1",
                    (community, character),
                ).fetchone()
                if active:
                    continue
                init = connection.execute(
                    "SELECT * FROM memory_initializations WHERE character_id=?", (character,)
                ).fetchone()
                if scope["memory_status"] == "preparing" and init["view_run_id"]:
                    run = self.coordinator.runs.get(
                        connection, community, character, init["view_run_id"]
                    )
                    if run.status in ("failed", "partial", "cancelled"):
                        if init["attempts"] and run.status != "cancelled":
                            connection.execute(
                                "UPDATE memory_initializations SET attempts=attempts-1 "
                                "WHERE character_id=?",
                                (character,),
                            )
                            if run.status == "partial":
                                resumed = supplement(self.coordinator, connection, run, now)
                            else:
                                resumed = self.coordinator._resume(connection, run, now)
                                if resumed.status == "failed":
                                    snapshot = self.coordinator.runs.snapshot(
                                        connection, community, character, str(run.graph_run_id)
                                    )
                                    resumed = self.coordinator.start_snapshot_in(
                                        connection, snapshot, now
                                    )
                            connection.execute(
                                "UPDATE memory_initializations SET view_run_id=? "
                                "WHERE character_id=?",
                                (str(resumed.graph_run_id), character),
                            )
                            return True
                        InitializationRepository().fail(
                            connection, character, "core_view_failed", now
                        )
                        return True
                elif connection.execute(
                    "SELECT 1 FROM reflection_graph_runs r WHERE r.community_id=? "
                    "AND r.character_id=? "
                    "AND r.graph_kind='view_refresh' AND r.status='partial' "
                    "AND NOT EXISTS (SELECT 1 FROM reflection_supplements s "
                    "JOIN reflection_graph_runs child ON child.graph_run_id=s.graph_run_id "
                    "WHERE s.original_run_id=r.graph_run_id AND child.status='completed')",
                    (community, character),
                ).fetchone():
                    continue
                policy = self.coordinator.context.graph.policy
                batch = self.changes.freeze(
                    connection,
                    community,
                    character,
                    now,
                    max_count=policy.max_materials,
                    max_chars=policy.max_material_chars,
                )
                if batch is None:
                    if scope["memory_status"] == "preparing":
                        InitializationRepository().advance(connection, character, "completed", now)
                        return True
                    continue
                materials = tuple(
                    FactMaterial.model_validate(item)
                    for item in json.loads(batch["materials_json"])
                )
                if not materials:
                    connection.execute(
                        "UPDATE memory_change_batches SET outcome='no_op',consumed_at_utc=? "
                        "WHERE batch_id=?",
                        (utc_text(now), batch["batch_id"]),
                    )
                    return True
                snapshot = self.coordinator.context.graph.prepare(
                    connection,
                    community,
                    character,
                    None,
                    0,
                    ReflectionGraphKind.VIEW_REFRESH,
                    "memory_change_set",
                    batch["batch_id"],
                    batch["source_version"],
                    materials,
                    now,
                )
                run = self.coordinator.start_snapshot_in(connection, snapshot, now)
                if scope["memory_status"] == "preparing":
                    connection.execute(
                        "UPDATE memory_initializations SET view_run_id=?,attempts=0 "
                        "WHERE character_id=?",
                        (str(run.graph_run_id), character),
                    )
                return True
        return False
