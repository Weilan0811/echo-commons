import asyncio
from datetime import UTC, datetime

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text


class ConversationInputReadiness:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def check(self, invocation: AgentInvocation) -> None:
        await asyncio.to_thread(self._check, invocation)

    def _check(self, invocation: AgentInvocation) -> None:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT t.status,t.attempt_count,t.lease_until_utc,t.snapshot_id,"
                "c.status AS community_status,v.status AS conversation_status,"
                "s.status AS turn_status,ch.status AS chain_status "
                "FROM conversation_tasks t JOIN communities c USING(community_id) "
                "JOIN conversations v USING(conversation_id) "
                "JOIN social_turns s ON s.social_turn_id=t.social_turn_id "
                "LEFT JOIN social_chains ch ON ch.chain_id=s.chain_id WHERE t.task_id=?",
                (invocation.scope.task_id,),
            ).fetchone()
            if row["community_status"] != "active":
                raise ExecutionDeferred()
            if (
                row["status"] != "processing"
                or row["attempt_count"] != invocation.identity.attempt
                or row["snapshot_id"] != invocation.context_input.snapshot_id
                or row["lease_until_utc"] is None
                or row["lease_until_utc"] <= utc_text(datetime.now(UTC))
                or row["conversation_status"] != "active"
                or row["turn_status"] != "running"
                or row["chain_status"] not in (None, "active")
            ):
                raise LeaseLostError("Conversation task is no longer ready for model execution")
