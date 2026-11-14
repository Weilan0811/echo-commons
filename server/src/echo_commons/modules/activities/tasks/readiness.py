import asyncio

from echo_commons.execution.clock import utc_now
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.mapping import utc_datetime


class ActivityReadiness:
    def __init__(self, database, tasks, review):
        self.database, self.tasks, self.review = database, tasks, review

    def check_in(self, connection, lease):
        row = self.tasks.owned(connection, lease, utc_now())
        if row is None:
            raise LeaseLostError("Activity task is no longer owned")
        self._source(connection, row)
        return row

    def _source(self, connection, row):
        code = self.review.source_code(connection, row)
        if code in ("community_paused", "character_unavailable"):
            raise ExecutionDeferred(code)
        if code:
            raise LeaseLostError(code)

    async def check(self, invocation):
        await asyncio.to_thread(
            self.check_task, invocation.scope.task_id, invocation.identity.attempt
        )

    def check_task(self, task_id, attempt):
        with self.database.read() as connection:
            row = self.tasks.get(connection, task_id)
            if (
                row["status"] != "processing"
                or row["attempt_count"] != attempt
                or row["lease_until_utc"] is None
                or utc_datetime(row["lease_until_utc"]) <= utc_now()
            ):
                raise LeaseLostError("Activity task execution changed or expired")
            self._source(connection, row)


class ExpressionReadiness:
    def __init__(self, turn, expression):
        self.turn, self.expression = turn, expression

    async def check(self, invocation):
        readiness = (
            self.turn if invocation.scope.source_kind == "activity_decision" else self.expression
        )
        await readiness.check(invocation)
