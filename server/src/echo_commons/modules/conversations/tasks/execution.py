from datetime import datetime
from uuid import UUID

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
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_MESSAGE_CONTRACT,
)
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import ContextInputRef
from echo_commons.agents.contracts.run import AgentRunResult
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.services.registry import AgentRegistry
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery


class ConversationExecution:
    def __init__(
        self,
        database: Database,
        tasks: ConversationTaskRepository,
        agents: AgentRegistry,
        limits: ExecutionLimits,
        recovery: ConversationRecovery,
    ) -> None:
        self.recovery = recovery
        self.database, self.tasks, self.agents, self.limits = database, tasks, agents, limits

    def prepare(
        self, task_id: str, *, attempt: int, deadline_utc: datetime | None = None
    ) -> PreparedExecution:
        with self.database.read() as connection:
            task = self.tasks.get(connection, task_id)
            InstanceRepository().get(
                connection, task["community_id"], task["character_id"]
            ).require_ready()
            snapshot = self.tasks.snapshot(connection, task_id)
            scope = snapshot.scope
            if (
                task["community_id"],
                task["character_id"],
                task["conversation_id"],
                task["membership_id"],
                task["social_turn_id"],
                task["initiation_id"],
            ) != (
                scope.community_id,
                scope.character_id,
                scope.conversation_id,
                scope.membership_id,
                scope.social_turn_id,
                scope.initiation_id,
            ):
                raise ExecutionError("task_snapshot_identity_mismatch", FailureCategory.SOURCE)
            agent = self.agents.resolve(
                connection,
                scope.community_id,
                scope.character_id,
                purpose=InvocationPurpose.CONVERSATION_REPLY,
            )
            route = agent.route_for("conversation_reply")
            invocation = AgentInvocation(
                identity=InvocationIdentity(
                    agent_id=agent.descriptor.agent_id,
                    purpose=InvocationPurpose.CONVERSATION_REPLY,
                    attempt=attempt,
                ),
                scope=InvocationScope(
                    community_id=scope.community_id,
                    character_id=scope.character_id,
                    task_id=task_id,
                    source_kind="social_turn",
                    source_id=scope.social_turn_id,
                ),
                context=snapshot,
                context_input=ContextInputRef(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_schema_version=snapshot.schema_version,
                ),
                output_contract=(
                    CHARACTER_EXPRESSION_CONTRACT
                    if CHARACTER_EXPRESSION_CONTRACT in snapshot.action_space.output_contracts
                    else CHARACTER_MESSAGE_CONTRACT
                ),
                execution_policy=ExecutionPolicy(
                    **(
                        {
                            "model_entry_id": snapshot.memory.input_budget.model_entry_id,
                            "model_configuration": snapshot.memory.input_budget.model_configuration,
                        }
                        if snapshot.memory.input_budget is not None
                        else {}
                    ),
                    allowed_tools=snapshot.action_space.tools,
                    model_profile=route.resolved_profile,
                    max_model_steps=self.limits.model_steps,
                    max_model_requests=self.limits.model_requests,
                    max_tool_calls=self.limits.tool_calls,
                    max_output_tokens=(
                        snapshot.memory.input_budget.output_tokens
                        if snapshot.memory.input_budget is not None
                        else self.limits.max_output_tokens
                    ),
                    max_input_chars=self.limits.max_input_chars,
                    temperature=self.limits.temperature,
                    top_p=self.limits.top_p,
                    deadline_utc=deadline_utc,
                    output_instructions=(
                        snapshot.memory.input_budget.output_instructions
                        if snapshot.memory.input_budget is not None
                        else self.limits.output_instructions
                    ),
                    repair_hint=self.recovery.hint(connection, task_id),
                ),
                correlation=Correlation(task_id=task_id, trace_id=UUID(task["trace_id"])),
            )
        return PreparedExecution(agent, invocation)

    async def execute(
        self, task_id: str, *, attempt: int, deadline_utc: datetime | None = None
    ) -> AgentRunResult:
        prepared = self.prepare(task_id, attempt=attempt, deadline_utc=deadline_utc)
        return await prepared.agent.run(prepared.invocation)
