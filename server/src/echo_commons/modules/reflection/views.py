import asyncio
import json
from uuid import UUID, uuid5

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.services.view_materials import ViewMaterialPreparation
from echo_commons.modules.reflection.contracts.context import FactMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.modules.reflection.policy import require_graph
from echo_commons.modules.reflection.supplements import supplement
from echo_commons.shared.errors import ConflictError


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
                policy = self.coordinator.context.graph.policy
                batch = ViewMaterialPreparation().freeze(
                    connection,
                    self.changes,
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
                usable = tuple(
                    item
                    for item in materials
                    if item.fact_kind != "relationship"
                    or (
                        json.loads(item.content)["relationship_type"] != "stranger"
                        and json.loads(item.content)["evidence"]
                    )
                )
                if len(usable) != len(materials):
                    # 缺少证据的关系保留诊断记录，其余正式事实继续处理。
                    materials = usable
                    connection.execute(
                        "UPDATE memory_change_batches SET materials_json=? WHERE batch_id=?",
                        (
                            json.dumps(
                                [item.model_dump(mode="json") for item in materials],
                                ensure_ascii=False,
                            ),
                            batch["batch_id"],
                        ),
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
                connection.execute(
                    "UPDATE memory_core_refreshes SET graph_run_id=? WHERE batch_id=?",
                    (str(run.graph_run_id), batch["batch_id"]),
                )
                connection.execute(
                    "UPDATE memory_relationship_refreshes SET graph_run_id=? WHERE batch_id=?",
                    (str(run.graph_run_id), batch["batch_id"]),
                )
                if scope["memory_status"] == "preparing":
                    connection.execute(
                        "UPDATE memory_initializations SET view_run_id=?,attempts=0 "
                        "WHERE character_id=?",
                        (str(run.graph_run_id), character),
                    )
                return True
        return False

    def refresh_relationships(self, community_id, character_id, request_id, target=None):
        with self.database.transaction() as connection:
            now = utc_now()
            instance = InstanceRepository().get(connection, community_id, character_id)
            require_graph(instance, ReflectionGraphKind.VIEW_REFRESH)
            requested_target = json.dumps(
                dict(kind=target.kind.value, actor_id=target.actor_id) if target else None,
                sort_keys=True,
            )
            existing = connection.execute(
                "SELECT * FROM memory_relationship_refreshes WHERE request_id=?",
                (request_id,),
            ).fetchall()
            if existing:
                if any(
                    (row["community_id"], row["character_id"], row["request_target_json"])
                    != (community_id, character_id, requested_target)
                    for row in existing
                ):
                    raise ConflictError("Relationship refresh request scope differs")
                return self._relationship_results(existing)
            facts = [
                fact
                for fact in self.changes.facts(connection, community_id, character_id, now)
                if fact["fact_kind"] == "relationship"
                and json.loads(fact["content"])["relationship_type"] != "stranger"
                and (
                    target is None
                    or fact["source_id"] == f"{character_id}/{target.kind.value}/{target.actor_id}"
                )
            ]
            if not facts:
                raise ConflictError("No initialized relationship is available to refresh")
            policy = self.coordinator.context.graph.policy
            for fact in facts:
                batch_id = str(uuid5(UUID(request_id), fact["source_id"]))
                material = ViewMaterialPreparation().relationship(
                    connection,
                    community_id,
                    character_id,
                    fact,
                    now,
                    policy.max_material_chars,
                )
                content = json.loads(material["content"])
                self.changes.create_batch(
                    connection,
                    community_id,
                    character_id,
                    batch_id,
                    request_id,
                    [material],
                    [],
                    None,
                    now,
                )
                connection.execute(
                    "UPDATE memory_relationship_refreshes SET request_kind='manual',"
                    "request_id=?,request_target_json=? WHERE batch_id=?",
                    (request_id, requested_target, batch_id),
                )
                if not content["evidence"]:
                    connection.execute(
                        "UPDATE memory_change_batches SET outcome='no_op',consumed_at_utc=? "
                        "WHERE batch_id=?",
                        (utc_text(now), batch_id),
                    )
                    continue
                snapshot = self.coordinator.context.graph.prepare(
                    connection,
                    community_id,
                    character_id,
                    None,
                    0,
                    ReflectionGraphKind.VIEW_REFRESH,
                    "memory_change_set",
                    batch_id,
                    request_id,
                    (FactMaterial.model_validate(material),),
                    now,
                )
                run = self.coordinator.start_snapshot_in(connection, snapshot, now)
                connection.execute(
                    "UPDATE memory_relationship_refreshes SET graph_run_id=? WHERE batch_id=?",
                    (str(run.graph_run_id), batch_id),
                )
            rows = connection.execute(
                "SELECT * FROM memory_relationship_refreshes WHERE request_id=?",
                (request_id,),
            ).fetchall()
            return self._relationship_results(rows)

    def _relationship_results(self, rows):
        return [
            dict(
                target=dict(kind=row["target_kind"], actor_id=row["target_id"]),
                graph_run_id=row["graph_run_id"],
                error_code=row["error_code"],
                source_version=row["source_version"],
            )
            for row in rows
        ]

    def refresh_core(self, community_id, character_id, request_id):
        coordinator = self.coordinator
        with self.database.transaction() as connection:
            now = utc_now()
            instance = InstanceRepository().get(connection, community_id, character_id)
            require_graph(instance, ReflectionGraphKind.VIEW_REFRESH)
            existing = connection.execute(
                "SELECT * FROM memory_core_refreshes WHERE batch_id=?", (request_id,)
            ).fetchone()
            if existing:
                batch = self.changes.get(connection, community_id, character_id, request_id)
                if existing["graph_run_id"] is not None:
                    return coordinator.runs.get(
                        connection, community_id, character_id, existing["graph_run_id"]
                    )
                materials = json.loads(batch["materials_json"])
            else:
                policy = coordinator.context.graph.policy
                materials = ViewMaterialPreparation().select(
                    connection,
                    community_id,
                    character_id,
                    now,
                    set(),
                    max_count=policy.max_materials,
                    max_chars=policy.max_material_chars,
                    batch_id=request_id,
                    version=request_id,
                    fresh=True,
                )
                self.changes.create_batch(
                    connection,
                    community_id,
                    character_id,
                    request_id,
                    request_id,
                    materials,
                    [],
                    "manual",
                    now,
                )
            snapshot = coordinator.context.graph.prepare(
                connection,
                community_id,
                character_id,
                None,
                0,
                ReflectionGraphKind.VIEW_REFRESH,
                "memory_change_set",
                request_id,
                batch["source_version"] if existing else request_id,
                tuple(FactMaterial.model_validate(item) for item in materials),
                now,
            )
            run = coordinator.start_snapshot_in(connection, snapshot, now)
            connection.execute(
                "UPDATE memory_core_refreshes SET graph_run_id=? WHERE batch_id=?",
                (str(run.graph_run_id), request_id),
            )
            return run
