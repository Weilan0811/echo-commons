import asyncio
from datetime import UTC, datetime

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.reflection.contexts.sources import ReflectionSources
from echo_commons.modules.reflection.contracts.context import ReflectionNodeInput
from echo_commons.modules.reflection.policy import require_graph
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository


class ReflectionInputReadiness:
    def __init__(
        self,
        database: Database,
        nodes: NodeRepository,
        runs: RunRepository,
        communities: CommunityReader,
        instances: InstanceReader,
        sources: ReflectionSources,
    ) -> None:
        self.database, self.nodes, self.runs = database, nodes, runs
        self.communities, self.sources = communities, sources
        self.instances = instances

    async def check(self, invocation: AgentInvocation) -> None:
        await asyncio.to_thread(self._check, invocation)

    def _check(self, invocation: AgentInvocation) -> None:
        if not isinstance(invocation.context, ReflectionNodeInput):
            raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
        with self.database.read() as connection:
            node = self.nodes.get(connection, invocation.scope.task_id)
            run = self.runs.get(
                connection,
                invocation.scope.community_id,
                invocation.scope.character_id,
                str(node.graph_run_id),
            )
            if (
                run.is_terminal
                or node.status != "processing"
                or node.lease_until_utc is None
                or node.lease_until_utc <= datetime.now(UTC)
                or node.attempt_count != invocation.identity.attempt
                or str(node.graph_run_id) != invocation.context.graph_run_id
            ):
                raise LeaseLostError("Reflection node is no longer ready for model execution")
            if (
                self.communities.get(connection, run.community_id).status != "active"
                or self.instances.get(
                    connection, run.community_id, run.character_id
                ).availability_status
                != "available"
            ):
                raise ExecutionDeferred()
            self.sources.check_sources(connection, invocation.context.graph_snapshot)
            require_graph(
                self.instances.get(connection, run.community_id, run.character_id), run.graph_kind
            )
