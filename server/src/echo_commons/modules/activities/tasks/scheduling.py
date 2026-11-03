import asyncio

from echo_commons.execution.clock import utc_now


class ActivitySchedulingQueue:
    def __init__(self, tasks, expressions, *, task_weight, expression_weight):
        if task_weight < 1 or expression_weight < 1:
            raise ValueError("Activity queue weights must be positive")
        self.tasks, self.expressions = tasks, expressions
        self.task_weight, self.expression_weight = task_weight, expression_weight
        self.database, self.recorder = tasks.database, tasks.recorder

    async def claim(self, owner, now):
        return await asyncio.to_thread(self._claim, owner)

    def _claim(self, owner):
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            now = utc_now()
            self.tasks.lifecycle.reconcile_in(connection, now)
            position = connection.execute(
                "SELECT next_position FROM activity_scheduling WHERE scheduler_id=1"
            ).fetchone()[0]
            total = self.task_weight + self.expression_weight
            slot = position % total
            for _ in range(2):
                queue = self.tasks if slot < self.task_weight else self.expressions
                lease = queue.claim_in(connection, owner, now)
                if lease:
                    # 领取与推进位置共同提交，所有执行者共享同一轮询顺序。
                    connection.execute(
                        "UPDATE activity_scheduling SET next_position=? WHERE scheduler_id=1",
                        ((slot + 1) % total,),
                    )
                    return lease
                slot = self.task_weight if queue is self.tasks else 0
            return None

    def _queue(self, lease):
        return self.expressions if lease.task_kind == "activity_expression" else self.tasks

    async def renew(self, lease, now):
        return await self._queue(lease).renew(lease, now)

    async def recover(self, now):
        return await self.tasks.recover(now) + await self.expressions.recover(now)

    async def apply_recovery(self, lease, now, recovery, observation=None):
        return await self._queue(lease).apply_recovery(lease, now, recovery, observation)
