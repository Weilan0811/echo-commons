import sqlite3
from datetime import datetime

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    CheckedCharacterExpression,
    expression_message,
)
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import TaskLease
from echo_commons.modules.conversations.services.expression_review import ExpressionReview
from echo_commons.modules.conversations.services.expression_review import (
    ReviewPolicy as ReviewPolicy,
)


class ConversationReview(ExpressionReview):
    def check(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        task: sqlite3.Row,
        invocation: AgentInvocation,
        result: AgentRunResult,
        now: datetime,
    ) -> str | None:
        if (
            invocation.identity.purpose is not InvocationPurpose.CONVERSATION_REPLY
            or not isinstance(invocation.context, ContextSnapshot)
        ):
            return "invocation_identity_mismatch"
        scope = invocation.context.scope
        source = connection.execute(
            "SELECT t.status,c.status AS chain_status FROM social_turns t "
            "LEFT JOIN social_chains c ON c.chain_id=t.chain_id WHERE t.social_turn_id=?",
            (task["social_turn_id"],),
        ).fetchone()
        if source["status"] != "running" or source["chain_status"] not in (None, "active"):
            return "source_replaced"
        if (
            lease.task_id != invocation.scope.task_id
            or lease.attempt != invocation.identity.attempt
            or lease.trace_id != str(invocation.correlation.trace_id)
            or result.invocation_id != invocation.identity.invocation_id
            or result.agent_id != invocation.identity.agent_id
            or result.agent_kind != "character"
            or result.model_profile != invocation.execution_policy.model_profile
            or result.harness_version != invocation.execution_policy.harness_version
            or invocation.scope.source_kind != "social_turn"
            or invocation.scope.source_id != task["social_turn_id"]
            or scope.social_turn_id != task["social_turn_id"]
            or scope.initiation_id != task["initiation_id"]
            or task["snapshot_id"] != invocation.context_input.snapshot_id
            or task["character_id"] != invocation.scope.character_id
            or task["community_id"] != invocation.scope.community_id
            or task["conversation_id"] != scope.conversation_id
            or task["membership_id"] != scope.membership_id
        ):
            return "invocation_identity_mismatch"
        if result.status is AgentRunStatus.NO_PROPOSAL:
            return self.context(connection, invocation.context) or (
                "unexpected_silent_output" if result.output is not None else None
            )
        if result.status is not AgentRunStatus.COMPLETED or result.output is None:
            return "invalid_agent_result"
        if (
            result.output.contract != invocation.output_contract
            or not isinstance(
                result.output.payload, (CharacterMessageProposal, CheckedCharacterExpression)
            )
            or result.output.contract
            not in (CHARACTER_MESSAGE_CONTRACT, CHARACTER_EXPRESSION_CONTRACT)
        ):
            return "invalid_output_contract"
        return self.expression(
            connection, invocation.context, expression_message(result.output.payload)
        )
