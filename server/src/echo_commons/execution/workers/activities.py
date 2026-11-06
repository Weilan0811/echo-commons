import asyncio
import json

from pydantic import TypeAdapter

from echo_commons.execution.clock import utc_now
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.activities.coordination import ActivityCoordinator
from echo_commons.modules.activities.tasks.scheduling import ActivitySchedulingQueue


class ActivityWorker:
    def __init__(
        self,
        coordinator: ActivityCoordinator,
        queue: ActivitySchedulingQueue,
        dispatcher: TaskDispatcher,
    ) -> None:
        self.coordinator, self.queue, self.dispatcher = coordinator, queue, dispatcher

    async def run_once(self) -> bool:
        await asyncio.to_thread(self.coordinator.scan)
        await self.queue.recover(utc_now())
        return await self.dispatcher.dispatch_once()


class ActivityObservationWorker:
    def __init__(self, reactions):
        self.reactions = reactions

    async def run_once(self):
        await asyncio.to_thread(self.reactions.scan)
        # 扫描始终使用后台轮询间隔，机会产生后也不立即反复扫描。
        return False


class ActivityMemoryWorker:
    def __init__(self, context, expressions):
        self.context = context
        self.expressions = expressions

    async def run_once(self):
        with self.context.database.read() as connection:
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    "SELECT i.* FROM activity_inputs i JOIN activity_tasks t USING(input_id) "
                    "JOIN communities c ON c.community_id=t.community_id "
                    "WHERE t.status IN ('pending','retry_wait') AND c.status='active' "
                    "AND json_extract(i.memory_json,'$.memory.context_prepared')=0 "
                    "ORDER BY i.created_at_utc,i.input_id"
                )
            )
        for row in rows:
            request = json.loads(row["request_json"])
            suggestions = ()
            if request["suggested_actions"]:
                game = json.loads(row["preparation_json"])["evidence"]["game"]
                analyzer = self.context.gameplay.resolve(
                    game["game_type"], game["ruleset_id"], game["ruleset_version"]
                )
                suggestions = tuple(
                    TypeAdapter(analyzer.action_model).validate_python(a)
                    for a in request["suggested_actions"]
                )
            try:
                await self.context._prepare(
                    row["community_id"],
                    row["character_id"],
                    request["game_id"],
                    row["input_id"],
                    request["kind"],
                    request["participation_id"],
                    suggestions,
                )
            except ExecutionDeferred:
                continue
            with self.context.database.transaction() as connection:
                connection.execute(
                    "UPDATE activity_tasks SET available_at_utc=? WHERE input_id=? "
                    "AND status='retry_wait' AND last_error_code='memory_summary_pending'",
                    (utc_text(utc_now()), row["input_id"]),
                )
            return True
        return await self.expressions.prepare_waiting()
