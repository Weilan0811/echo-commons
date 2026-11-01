import json
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text


class ActivityResults:
    def for_task(self, connection, task_id):
        return connection.execute(
            "SELECT * FROM activity_results WHERE task_id=?", (task_id,)
        ).fetchone()

    def add(self, connection, task_id, artifact, receipt, expression, expression_status, now):
        identity = str(uuid4())
        connection.execute(
            "INSERT INTO activity_results(result_id,task_id,execution_mode,artifact_json,"
            "receipt_json,expression_json,expression_status,created_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                identity,
                task_id,
                artifact["mode"],
                json.dumps(artifact, ensure_ascii=False),
                receipt.model_dump_json() if receipt else None,
                expression.model_dump_json() if expression else None,
                expression_status,
                utc_text(now),
            ),
        )
        return identity
