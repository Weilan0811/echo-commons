import json
from uuid import uuid4

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import (
    content_fingerprint,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input


def _boundaries(connection, community, character, observed_at, current=None, upper=None):
    scenes = []
    for conversation in connection.execute(
        "SELECT DISTINCT v.conversation_id,v.kind FROM conversations v "
        "JOIN conversation_memberships m USING(conversation_id) WHERE v.community_id=? "
        "AND m.actor_kind='character' AND m.actor_id=? AND m.joined_at_utc<=? "
        "ORDER BY v.conversation_id",
        (community, character, observed_at),
    ):
        identity = conversation["conversation_id"]
        maximum = connection.execute(
            "SELECT COALESCE(max(sequence),0) FROM messages WHERE conversation_id=? "
            "AND created_at_utc<=?",
            (identity, observed_at),
        ).fetchone()[0]
        if identity == current:
            maximum = min(maximum, upper)
        scenes.append(
            dict(
                conversation_id=identity,
                kind=conversation["kind"],
                name="私聊" if conversation["kind"] == "direct" else "群聊",
                upper_sequence=maximum,
                membership_ids=[
                    row[0]
                    for row in connection.execute(
                        "SELECT membership_id FROM conversation_memberships WHERE "
                        "conversation_id=? "
                        "AND actor_kind='character' AND actor_id=? AND joined_at_utc<=?",
                        (identity, character, observed_at),
                    )
                ],
            )
        )
    return scenes


def _summary(connection, item):
    row = connection.execute(
        "SELECT * FROM memory_segments WHERE segment_id=?",
        (item.get("segment_id", item.get("source_id")),),
    ).fetchone()
    item.pop("first_sequence", None)
    item.pop("last_sequence", None)
    item.update(
        started_at_utc=row["started_at_utc"],
        ended_at_utc=row["ended_at_utc"],
        conversations=[
            json.loads(scene[0])
            for scene in connection.execute(
                "SELECT boundary_json FROM memory_segment_scenes WHERE segment_id=? "
                "ORDER BY conversation_id",
                (row["segment_id"],),
            )
        ],
    )


def _snapshot(connection, data):
    scope = data["scope"]
    chat = "perspective" in data
    current = scope.get("conversation_id") if chat else data.pop("conversation_id", None)
    upper = (
        scope.get("observation_upper_sequence")
        if chat
        else data.pop("observation_upper_sequence", 0)
    )
    scenes = _boundaries(
        connection,
        scope["community_id"],
        scope["character_id"],
        data["prepared_at_utc"],
        current,
        upper,
    )
    data["schema_version"] = 2
    if chat:
        data["perspective"].pop("root_message_ids", None)
        scope["conversations"] = scenes
        data["prompt_layout_version"] = 2
        for message in (*data["perspective"]["inputs"], *data["perspective"]["history"]):
            message["conversation_id"] = current
        for summary in data["memory"]["segment_summaries"]:
            _summary(connection, summary)
        return ContextSnapshot.model_validate(data)
    data["conversations"] = scenes
    for material in data["materials"]:
        if material["kind"] == "message":
            row = connection.execute(
                "SELECT conversation_id FROM messages WHERE message_id=?", (material["source_id"],)
            ).fetchone()
            material["message"]["conversation_id"] = row[0]
        elif material["kind"] == "thought":
            row = connection.execute(
                "SELECT conversation_id FROM thoughts WHERE thought_id=?", (material["source_id"],)
            ).fetchone()
            material["conversation_id"] = row[0]
        elif material["kind"] == "segment_summary":
            _summary(connection, material)
        elif material["kind"] == "conversation_digest":
            material.pop("covers_through_sequence", None)
    if data["graph_kind"] in ("segment_reflect", "continuity_compress"):
        for contract in data["action_space"]["output_contracts"]:
            if contract["kind"] == "reflection_node":
                contract["version"] = "v6"
    return GraphContextSnapshot.model_validate(data)


def _payload(data, snapshot):
    if isinstance(data, list):
        return [_payload(item, snapshot) for item in data]
    if not isinstance(data, dict):
        return data
    data = {key: _payload(value, snapshot) for key, value in data.items()}
    if data.get("kind") == "segment_summary":
        data.pop("first_message_sequence", None)
        data.pop("last_message_sequence", None)
        if "follow_up" in data:
            follow = data["follow_up"]
            targets = {}
            if follow["relationship_reflect"]:
                for material in snapshot.materials:
                    if material.kind != "message" or material.message.sender.kind == "system":
                        continue
                    actor = material.message.sender
                    if actor.kind == "character" and actor.actor_id == snapshot.scope.character_id:
                        continue
                    key = (actor.kind.value, actor.actor_id)
                    targets.setdefault(key, []).append(material.evidence_ref)
            follow["relationship_targets"] = [
                dict(target=dict(kind=kind, actor_id=identity), evidence_refs=references)
                for (kind, identity), references in targets.items()
            ]
            if not targets:
                follow["relationship_reflect"] = False
    elif data.get("kind") == "relationship_reflection":
        for dimension in data["dimensions"]:
            dimension["evidence_refs"] = data.get("evidence_refs", [])
    elif data.get("kind") == "continuity_digest":
        data.pop("covers_through_sequence", None)
        data.pop("content_version", None)
    return data


def migrate_experiences(connection, now):
    for row in tuple(connection.execute("SELECT * FROM conversation_tasks")):
        original = json.loads(row["snapshot_json"])
        snapshot = _snapshot(connection, json.loads(row["snapshot_json"]))
        connection.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                row["trace_id"],
                "task.input.migrated",
                "conversation_task",
                row["task_id"],
                json.dumps(
                    dict(
                        community_id=row["community_id"],
                        character_id=row["character_id"],
                        original_snapshot=original,
                    ),
                    ensure_ascii=False,
                ),
                now,
            ),
        )
        connection.execute(
            "UPDATE conversation_tasks SET snapshot_json=? WHERE task_id=?",
            (snapshot.model_dump_json(), row["task_id"]),
        )
        if row["status"] == "processing":
            connection.execute(
                "UPDATE conversation_tasks SET "
                "status='pending',lease_owner=NULL,lease_until_utc=NULL,"
                "lease_generation=lease_generation+1 WHERE task_id=?",
                (row["task_id"],),
            )
    for row in tuple(connection.execute("SELECT * FROM reflection_graph_runs")):
        identity = row["graph_run_id"]
        version = reflection_graph_definition(row["graph_kind"]).version
        if (
            row["graph_kind"] in ("memory_organize", "view_refresh")
            and row["graph_version"] != version
        ):
            # 已在此前迁移停用的协议只保留原审计，当前注册表不允许执行。
            continue
        original = json.loads(row["snapshot_json"])
        snapshot = _snapshot(connection, json.loads(row["snapshot_json"]))
        connection.execute(
            "INSERT INTO traces VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                row["trace_id"] or identity,
                "task.input.migrated",
                "reflection_graph",
                identity,
                json.dumps(
                    dict(
                        community_id=row["community_id"],
                        character_id=row["character_id"],
                        original_snapshot=original,
                        original_graph_version=row["graph_version"],
                    ),
                    ensure_ascii=False,
                ),
                now,
            ),
        )
        connection.execute(
            "UPDATE reflection_graph_runs SET "
            "snapshot_json=?,snapshot_fingerprint=?,graph_version=?,"
            "snapshot_schema_version=2 "
            "WHERE graph_run_id=?",
            (
                snapshot.model_dump_json(),
                str(content_fingerprint(snapshot.model_dump(mode="json"))),
                version,
                identity,
            ),
        )
        fingerprints = {}
        for artifact in tuple(
            connection.execute(
                "SELECT * FROM reflection_artifacts WHERE graph_run_id=?", (identity,)
            )
        ):
            payload = _payload(json.loads(artifact["payload_json"]), snapshot)
            audit = json.loads(artifact["audit_json"])
            audit["migration_original"] = dict(
                payload=json.loads(artifact["payload_json"]),
                output_contract_version=artifact["output_contract_version"],
                node_input_fingerprint=artifact["node_input_fingerprint"],
                evidence_refs=json.loads(artifact["evidence_refs_json"]),
            )
            contract = (
                "v6"
                if version == "v6" and artifact["output_contract_kind"] == "reflection_node"
                else artifact["output_contract_version"]
            )
            connection.execute(
                "UPDATE reflection_artifacts SET payload_json=?,content_fingerprint=?,audit_json=?,"
                "output_contract_version=? WHERE artifact_id=?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    artifact["content_fingerprint"],
                    json.dumps(audit, ensure_ascii=False),
                    contract,
                    artifact["artifact_id"],
                ),
            )
        updated_artifacts = {
            artifact["artifact_id"]: artifact
            for artifact in connection.execute(
                "SELECT * FROM reflection_artifacts WHERE graph_run_id=?",
                (identity,),
            )
        }

        def refresh_artifact(artifact_id, cache=fingerprints, records=updated_artifacts):
            if artifact_id in cache:
                return cache[artifact_id]
            artifact = records[artifact_id]
            refs = json.loads(artifact["evidence_refs_json"])
            for ref in refs:
                if ref["kind"] == "artifact" and ref["ref"] in records:
                    ref["version"] = refresh_artifact(ref["ref"])
            fingerprint = str(
                content_fingerprint(
                    dict(
                        output_contract=f"{artifact['output_contract_kind']}.{artifact['output_contract_version']}",
                        payload=json.loads(artifact["payload_json"]),
                        evidence_refs=refs,
                    )
                )
            )
            cache[artifact_id] = fingerprint
            connection.execute(
                "UPDATE reflection_artifacts SET evidence_refs_json=?,content_fingerprint=? "
                "WHERE artifact_id=?",
                (json.dumps(refs), fingerprint, artifact_id),
            )
            return fingerprint

        for artifact_id in updated_artifacts:
            refresh_artifact(artifact_id)
        nodes = NodeRepository()
        artifacts = ArtifactRepository()
        for node in nodes.for_graph(connection, identity):
            references = [
                dict(
                    artifact_id=str(ref.artifact_id),
                    content_fingerprint=fingerprints[str(ref.artifact_id)],
                )
                for ref in node.input_artifact_refs
            ]
            connection.execute(
                "UPDATE reflection_node_tasks SET input_artifact_refs_json=? WHERE node_task_id=?",
                (json.dumps(references), str(node.task_id)),
            )
            current = nodes.get(connection, str(node.task_id))
            inputs = artifacts.inputs(connection, identity, current.input_artifact_refs)
            context = prepare_node_input(
                snapshot,
                graph_run_id=identity,
                node_task_id=str(node.task_id),
                node_key=node.node_key,
                node_kind=node.node_kind,
                artifacts=inputs,
            )
            fingerprint = str(content_fingerprint(context.model_dump(mode="json")))
            contract = (
                "v6"
                if version == "v6" and node.output_contract.kind == "reflection_node"
                else node.output_contract.version
            )
            connection.execute(
                "UPDATE reflection_node_tasks SET "
                "node_input_fingerprint=?,output_contract_version=? "
                "WHERE node_task_id=?",
                (fingerprint, contract, str(node.task_id)),
            )
            connection.execute(
                "UPDATE reflection_artifacts SET node_input_fingerprint=? WHERE node_task_id=?",
                (fingerprint, str(node.task_id)),
            )
            if node.status in ("pending", "processing", "retry_wait"):
                connection.execute(
                    "UPDATE reflection_node_tasks SET "
                    "status='pending',lease_owner=NULL,lease_until_utc=NULL,"
                    "lease_generation=lease_generation+1,attempt_base_count=attempt_count "
                    "WHERE node_task_id=?",
                    (str(node.task_id),),
                )
        for result in tuple(
            connection.execute(
                "SELECT * FROM reflection_graph_results WHERE graph_run_id=?", (identity,)
            )
        ):
            payload = _payload(json.loads(result["payload_json"]), snapshot)
            aggregate = connection.execute(
                "SELECT a.content_fingerprint FROM reflection_artifacts a JOIN "
                "reflection_node_tasks n "
                "USING(node_task_id) WHERE a.graph_run_id=? AND n.node_key=? "
                "ORDER BY a.attempt DESC LIMIT 1",
                (identity, reflection_graph_definition(row["graph_kind"]).aggregate_node_key),
            ).fetchone()
            connection.execute(
                "UPDATE reflection_graph_results SET payload_json=?,aggregate_fingerprint=? "
                "WHERE result_id=?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    aggregate[0] if aggregate else result["aggregate_fingerprint"],
                    result["result_id"],
                ),
            )
