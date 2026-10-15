import json
from pathlib import Path

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize


def copy_to_historical_schema(source: Database, sql_directory: Path, path: Path) -> Database:
    # 将真实业务记录按历史列复制到真实旧库，避免当前业务入口依赖旧库不存在的字段。
    target = Database(path)
    initialize(target, sql_directory=sql_directory)
    connection = target.connect()
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ATTACH DATABASE ? AS current_data", (str(source.path),))
        connection.execute("BEGIN IMMEDIATE")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'memory_search_fts_%' AND name!='schema_migrations'"
            )
        ]
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            names = ",".join(f'"{name}"' for name in columns)
            connection.execute(f'DELETE FROM "{table}"')
            source_table = (
                "conversation_operations"
                if table == "conversation_membership_operations"
                else table
            )
            if table == "conversation_digests":
                source_table = "memory_digests"
            source_columns = {
                row[1]
                for row in connection.execute(f'PRAGMA current_data.table_info("{source_table}")')
            }
            if not source_columns:
                # 当前记录没有已删除的表，历史表保持空白。
                continue
            predicate = (
                " WHERE material_kind IN ('story','interview')"
                if table == "memory_author_materials"
                else " WHERE material_id IN (SELECT material_id FROM memory_author_materials)"
                if table == "memory_author_chunks"
                else ""
            )
            for row in connection.execute(
                f'SELECT * FROM current_data."{source_table}"' + predicate
            ):
                values = dict(row)
                if table == "memory_segments":
                    scene = historical_scene(connection, values["segment_id"])
                    values.update(
                        conversation_id=scene["conversation_id"],
                        first_message_sequence=scene["first_sequence"],
                        last_message_sequence=scene["last_sequence"],
                    )
                elif table == "memory_summary_batches":
                    scenes = {
                        historical_scene(connection, item[0])["conversation_id"]
                        for item in connection.execute(
                            "SELECT segment_id FROM current_data.memory_summary_batch_items WHERE batch_id=?",
                            (values["batch_id"],),
                        )
                    }
                    assert len(scenes) == 1
                    parents = [
                        item[0]
                        for item in connection.execute(
                            "SELECT digest_id FROM current_data.memory_summary_batch_digests WHERE batch_id=?",
                            (values["batch_id"],),
                        )
                    ]
                    assert len(parents) <= 1
                    values.update(
                        conversation_id=scenes.pop(),
                        previous_digest_id=parents[0] if parents else None,
                    )
                elif table == "conversation_digests":
                    values["covers_through_sequence"] = max(
                        historical_scene(connection, item[0])["last_sequence"]
                        for item in connection.execute(
                            "SELECT segment_id FROM current_data.memory_digest_segments WHERE digest_id=?",
                            (values["digest_id"],),
                        )
                    )
                if "snapshot_json" in values:
                    values["snapshot_schema_version"] = 1
                    values["snapshot_json"] = historical_snapshot(
                        connection, json.loads(values["snapshot_json"])
                    )
                if table == "reflection_graph_runs" and values["graph_version"] == "v6":
                    values["graph_version"] = "v4"
                if table == "reflection_node_tasks" and values["output_contract_version"] == "v6":
                    values["output_contract_version"] = "v4"
                connection.execute(
                    f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in columns)})',
                    tuple(values[column] for column in columns),
                )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.commit()
    finally:
        connection.close()
    return target


def historical_scene(connection, segment):
    rows = connection.execute(
        "SELECT * FROM current_data.memory_segment_scenes WHERE segment_id=?", (segment,)
    ).fetchall()
    assert len(rows) == 1
    return dict(rows[0])


def historical_snapshot(connection, data):
    data["schema_version"] = 1
    if "perspective" in data:
        data["prompt_layout_version"] = 1
        data["scope"].pop("conversations")
        messages = (*data["perspective"]["history"], *data["perspective"]["inputs"])
    else:
        for contract in data["action_space"]["output_contracts"]:
            if contract["version"] == "v6":
                contract["version"] = "v4"
        scenes = data.pop("conversations")
        if data["source_kind"] in ("author_material_batch", "memory_change_set"):
            data.update(conversation_id=None, observation_upper_sequence=0)
        else:
            assert len(scenes) == 1
            data.update(
                conversation_id=scenes[0]["conversation_id"],
                observation_upper_sequence=scenes[0]["upper_sequence"],
            )
        messages = [item["message"] for item in data["materials"] if item["kind"] == "message"]
        for material in data["materials"]:
            assert not material.pop("context_only", False)
            if material["kind"] == "thought":
                material.pop("conversation_id")
            elif material["kind"] == "segment_summary":
                scene = historical_scene(connection, material["source_id"])
                material.update(
                    first_sequence=scene["first_sequence"], last_sequence=scene["last_sequence"]
                )
                for field in ("started_at_utc", "ended_at_utc", "conversations"):
                    material.pop(field)
    for message in messages:
        message.pop("conversation_id")
        message.pop("visibility", None)
    for item in (*data["memory"]["resident"], *data["memory"]["recalled"]):
        item.pop("context_label", None)
    for summary in data["memory"]["segment_summaries"]:
        scene = historical_scene(connection, summary["segment_id"])
        summary.update(first_sequence=scene["first_sequence"], last_sequence=scene["last_sequence"])
        for field in ("started_at_utc", "ended_at_utc", "conversations"):
            summary.pop(field)
    return json.dumps(data, ensure_ascii=False)
