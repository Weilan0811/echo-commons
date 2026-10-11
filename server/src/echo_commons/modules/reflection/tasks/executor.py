from datetime import datetime

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.execution import ExecutionLimits, PreparedExecution
from echo_commons.agents.contracts.invocation import (
    AgentInvocation,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    InvocationScope,
)
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import ContextInputRef, OutputContractRef
from echo_commons.agents.contracts.run import AgentRunResult
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.services.registry import AgentRegistry
from echo_commons.modules.reflection.budget import ReflectionBudget
from echo_commons.modules.reflection.domain.graph import (
    ReflectionExecutionKind,
    content_fingerprint,
)
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.recovery import ReflectionRecovery


class ReflectionExecution:
    def __init__(
        self,
        database: Database,
        nodes: NodeRepository,
        runs: RunRepository,
        artifacts: ArtifactRepository,
        registry: ReflectionGraphRegistry,
        agents: AgentRegistry,
        limits: ExecutionLimits,
        recovery: ReflectionRecovery,
        budget: ReflectionBudget | None = None,
    ) -> None:
        self.database, self.nodes, self.runs, self.artifacts = database, nodes, runs, artifacts
        self.recovery = recovery
        self.registry, self.agents, self.limits = registry, agents, limits
        self.budget = budget or ReflectionBudget()

    def prepare(
        self,
        task_id: str,
        *,
        attempt: int,
        deadline_utc: datetime | None = None,
    ) -> PreparedExecution:
        with self.database.read() as connection:
            node = self.nodes.get(connection, task_id)
            scope = self.runs.scope(connection, str(node.graph_run_id))
            run = self.runs.get(
                connection, scope.community_id, scope.character_id, str(node.graph_run_id)
            )
            definition = self.registry.require(run.graph_kind, run.graph_version).node(
                node.node_key
            )
            if definition.execution_kind is not ReflectionExecutionKind.MODEL:
                raise ValueError("Reflection node does not execute a model")
            if node.status != "processing" or node.attempt_count != attempt or run.is_terminal:
                raise LeaseLostError("Reflection node is not a current model task")
            snapshot = self.runs.snapshot(
                connection, scope.community_id, scope.character_id, str(node.graph_run_id)
            )
            inputs = self.artifacts.inputs(
                connection, str(node.graph_run_id), node.input_artifact_refs
            )
            context = prepare_node_input(
                snapshot,
                graph_run_id=str(node.graph_run_id),
                node_task_id=task_id,
                node_key=node.node_key,
                node_kind=node.node_kind,
                artifacts=inputs,
            )
            if content_fingerprint(context.model_dump(mode="json")) != node.node_input_fingerprint:
                raise ExecutionError("reflection_input_mismatch", FailureCategory.SOURCE)
            agent = self.agents.resolve(
                connection,
                scope.community_id,
                scope.character_id,
                purpose=InvocationPurpose.REFLECTION,
            )
            count_limit, char_limit = self.budget.node_limits(snapshot, node.node_key)
            invocation = AgentInvocation(
                identity=InvocationIdentity(
                    agent_id=agent.descriptor.agent_id,
                    purpose=InvocationPurpose.REFLECTION,
                    attempt=attempt,
                ),
                scope=InvocationScope(
                    community_id=scope.community_id,
                    character_id=scope.character_id,
                    task_id=task_id,
                    source_kind="reflection_graph",
                    source_id=str(node.graph_run_id),
                ),
                context=context,
                context_input=ContextInputRef(snapshot_id=context.snapshot_id),
                output_contract=OutputContractRef(
                    kind=node.output_contract.kind, version=node.output_contract.version
                ),
                execution_policy=ExecutionPolicy(
                    allowed_tools=context.action_space.tools,
                    model_profile=agent.route_for("reflection").resolved_profile,
                    max_model_steps=self.limits.model_steps,
                    max_model_requests=self.limits.model_requests,
                    max_tool_calls=self.limits.tool_calls,
                    max_output_tokens=self.limits.max_output_tokens,
                    max_content_chars=(
                        self.budget.core_memory_max_chars
                        if node.node_key == "core_memory_view" else None
                    ),
                    temperature=self.limits.temperature,
                    top_p=self.limits.top_p,
                    output_instructions=(
                        f"{self.limits.output_instructions or ''}\n"
                        f"本节点业务输出最多 {char_limit} 字符，来源引用单独校验。"
                        f"记忆页、实体与关系边合计最多 {count_limit} 项，合并重复内容。"
                    ),
                    deadline_utc=deadline_utc,
                    repair_hint=self.recovery.hint(connection, task_id, run.execution_generation),
                ),
                correlation=Correlation(task_id=task_id, trace_id=run.trace_id),
            )
        return PreparedExecution(agent, invocation)

    async def execute(
        self,
        task_id: str,
        *,
        attempt: int,
        deadline_utc: datetime | None = None,
    ) -> AgentRunResult:
        prepared = self.prepare(task_id, attempt=attempt, deadline_utc=deadline_utc)
        return await prepared.agent.run(prepared.invocation)
