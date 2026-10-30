import json

from echo_commons.agents.contracts.activity import ActivityScope
from echo_commons.modules.activities.domain.task import task_view
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import PageOptions, read_page


class ActivityManagement:
    def __init__(self, database, context, tasks, results, recorder):
        self.database, self.context, self.tasks, self.results, self.recorder = (
            database,
            context,
            tasks,
            results,
            recorder,
        )

    def list(self, community_id, character_id, options):
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            return read_page(
                connection,
                "SELECT task_id,community_id,character_id,game_id,participation_id,opportunity_id,"
                "status,mode,attempt_count,last_error_code,created_at_utc,updated_at_utc "
                "FROM activity_tasks WHERE community_id=? AND character_id=?",
                (community_id, character_id),
                scope={
                    "query": "activity_tasks",
                    "community_id": community_id,
                    "character_id": character_id,
                },
                order=("created_at_utc", "task_id"),
                options=options,
            )

    def detail(self, community_id, character_id, task_id):
        with self.database.read() as connection:
            row = self.tasks.get(connection, task_id)
            if (row["community_id"], row["character_id"]) != (community_id, character_id):
                raise NotFoundError("Activity task is outside this management scope")
            result = self.results.for_task(connection, task_id)
            view = task_view(row)
            scope = ActivityScope(
                community_id=community_id,
                character_id=character_id,
                game_id=row["game_id"],
                participation_id=row["participation_id"],
                seat_id=view.viewer_seat_id,
                conversation_id=row["conversation_id"],
                membership_id=row["membership_id"],
            )
            data = dict(row)
            for key in tuple(data):
                if key.endswith("_json"):
                    data[key[:-5]] = json.loads(data.pop(key)) if row[key] else None
            input_row = self.context.inputs.find(
                connection, community_id, character_id, row["input_id"]
            )
            return {
                "task": data,
                "input": json.loads(input_row["snapshot_json"])
                if input_row and input_row["snapshot_json"]
                else None,
                "result": {
                    k[:-5] if k.endswith("_json") else k: json.loads(v)
                    if k.endswith("_json") and v
                    else v
                    for k, v in dict(result).items()
                }
                if result
                else None,
                "working_memory": self.context.working_memory.current_in(
                    connection, scope
                ).model_dump(mode="json"),
                "execution": self.recorder.repository.history(
                    connection,
                    "activity_turn",
                    task_id,
                    community_id,
                    character_id,
                    PageOptions(limit=200),
                ),
            }
