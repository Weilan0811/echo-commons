import asyncio
from datetime import timedelta

from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import with_heartbeat
from echo_commons.execution.recovery import decide_run
from echo_commons.modules.reflection.domain.graph import ReflectionExecutionKind
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.tasks.commit import ReflectionNodeCommit
from echo_commons.modules.reflection.tasks.executor import ReflectionExecution
from echo_commons.modules.reflection.tasks.graph_commit import ReflectionGraphCommit
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue


class ReflectionHandler:
    def __init__(
        self,
        execution: ReflectionExecution,
        commit: ReflectionNodeCommit,
        graph_commit: ReflectionGraphCommit,
        queue: ReflectionQueue,
        registry: ReflectionGraphRegistry,
        heartbeat_seconds: float,
        execution_timeout_seconds: float,
    ) -> None:
        self.execution, self.commit, self.graph_commit = execution, commit, graph_commit
        self.queue, self.registry = queue, registry
        self.heartbeat_seconds, self.execution_timeout_seconds = (
            heartbeat_seconds,
            execution_timeout_seconds,
        )

    async def execute(self, lease: TaskLease) -> ExecutionOutcome:
        return await with_heartbeat(self.queue, lease, self._execute(lease), self.heartbeat_seconds)

    def _execution_kind(self, lease: TaskLease) -> ReflectionExecutionKind:
        with self.queue.database.read() as connection:
            node = self.queue.nodes.get(connection, lease.task_id)
            run = self.queue.run_for(connection, node)
            return (
                self.registry.require(run.graph_kind, run.graph_version)
                .node(node.node_key)
                .execution_kind
            )

    async def _execute(self, lease: TaskLease) -> ExecutionOutcome:
        kind = await asyncio.to_thread(self._execution_kind, lease)
        if kind is ReflectionExecutionKind.AGGREGATE:
            await asyncio.to_thread(self.graph_commit.commit, lease, utc_now())
            return ExecutionOutcome(Disposition.COMPLETED)
        prepared = await asyncio.to_thread(
            self.execution.prepare,
            lease.task_id,
            attempt=lease.attempt,
            deadline_utc=utc_now() + timedelta(seconds=self.execution_timeout_seconds),
        )
        result = await prepared.agent.run(prepared.invocation)
        outcome = decide_run(result)
        if outcome.disposition is not Disposition.COMPLETED:
            return outcome
        await asyncio.to_thread(self.commit.commit, lease, prepared.invocation, result, utc_now())
        return ExecutionOutcome(Disposition.COMPLETED)
