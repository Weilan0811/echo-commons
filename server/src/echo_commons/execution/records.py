import logging
import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import AgentRunResult, UsageSummary
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import (
    EventKind,
    ExecutionEventPayload,
    ExecutionObservation,
)
from echo_commons.execution.recovery import AppliedRecovery
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.execution_records import ExecutionRecordRepository
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.observability.outbox import enqueue_trace

logger = logging.getLogger("echo_commons.execution")


class ExecutionRecorder:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = ExecutionRecordRepository()

    def record(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        kind: EventKind,
        payload: ExecutionEventPayload,
        now: datetime,
        invocation_id: str | None = None,
    ) -> None:
        if lease.task_kind == "activity_expression":
            row = connection.execute(
                "SELECT t.community_id,t.character_id FROM activity_expression_tasks e "
                "JOIN activity_results r ON r.result_id=e.task_id JOIN activity_tasks t ON "
                "t.task_id=r.task_id WHERE e.task_id=?",
                (lease.task_id,),
            ).fetchone()
            graph_id, graph_generation = None, None
        elif lease.task_kind in ("activity_turn", "activity_reply"):
            row = connection.execute(
                "SELECT community_id,character_id FROM activity_tasks WHERE task_id=?",
                (lease.task_id,),
            ).fetchone()
            graph_id, graph_generation = None, None
        elif lease.task_kind in ("conversation_reply", "social_willingness"):
            row = connection.execute(
                "SELECT community_id,character_id FROM conversation_tasks WHERE task_id=?",
                (lease.task_id,),
            ).fetchone()
            graph_id, graph_generation = None, None
        else:
            row = connection.execute(
                "SELECT r.community_id,r.character_id,r.graph_run_id,r.execution_generation "
                "FROM reflection_node_tasks n JOIN reflection_graph_runs r USING(graph_run_id) "
                "WHERE n.node_task_id=?",
                (lease.task_id,),
            ).fetchone()
            graph_id = row["graph_run_id"]
            graph_generation = lease.graph_execution_generation
        identity = dict(
            event_kind=kind,
            task_kind=lease.task_kind,
            task_id=lease.task_id,
            attempt=lease.attempt,
            lease_generation=lease.generation,
            community_id=row["community_id"],
            character_id=row["character_id"],
            graph_run_id=graph_id,
            graph_execution_generation=graph_generation,
            invocation_id=invocation_id,
            trace_id=lease.trace_id,
            recorded_at_utc=utc_text(now),
        )
        self.repository.add(connection, identity, payload)
        enqueue_trace(
            connection,
            str(uuid4()),
            lease.trace_id,
            f"execution.{kind}",
            "task" if graph_id is None else "reflection_node",
            lease.task_id,
            {**identity, **payload.model_dump(mode="json")},
            now,
        )
        fields = dict(
            task_id=lease.task_id,
            task_kind=lease.task_kind,
            attempt=lease.attempt,
            generation=lease.generation,
            graph_run_id=graph_id,
            repair_hint_used=payload.repair_hint_used is not None,
        )
        if payload.recovery:
            applied = payload.recovery
            fields.update(
                error_code=applied.decision.failure.code,
                failure_category=applied.decision.failure.category.value,
                recovery_action=applied.action.value,
                retry_exhausted=applied.retry_exhausted,
                retry_delay_seconds=applied.effective_wait_seconds,
            )
        logger.info("Execution event %s", kind, extra=fields)

    def started(self, lease: TaskLease, invocation: AgentInvocation, now: datetime) -> None:
        with self.database.transaction() as connection:
            now = utc_now()
            self.record(
                connection,
                lease,
                "invocation_started",
                ExecutionEventPayload(repair_hint_used=invocation.execution_policy.repair_hint),
                now,
                str(invocation.identity.invocation_id),
            )

    def lifecycle(self, connection: sqlite3.Connection, rows, reason: str, now: datetime) -> None:
        for row in rows:
            current = connection.execute(
                ("SELECT status,lease_generation FROM conversation_tasks WHERE task_id=?"),
                (row["task_id"],),
            ).fetchone()
            if (current["status"], current["lease_generation"]) == (
                row["status"],
                row["lease_generation"],
            ):
                continue
            lease = TaskLease(
                row["task_id"],
                "conversation_reply",
                row["attempt_count"],
                current["lease_generation"],
                row["lease_owner"] or "lifecycle",
                now,
                row["trace_id"],
            )
            self.record(
                connection,
                lease,
                "lifecycle_changed",
                ExecutionEventPayload(reason_code=reason, task_state=current["status"]),
                now,
            )

    def ignored(self, lease: TaskLease, now: datetime) -> None:
        with self.database.transaction() as connection:
            now = utc_now()
            self.record(
                connection,
                lease,
                "result_ignored",
                ExecutionEventPayload(reason_code="lease_lost"),
                now,
            )

    def node_transition(self, connection, node, run, reason: str, now: datetime) -> None:
        lease = TaskLease(
            str(node.task_id),
            "reflection",
            node.attempt_count,
            node.lease_generation,
            node.lease_owner or "lifecycle",
            now,
            str(run.trace_id),
            run.execution_generation,
        )
        self.record(
            connection,
            lease,
            "lifecycle_changed",
            ExecutionEventPayload(reason_code=reason, task_state=node.status),
            now,
        )

    def recovery_payload(
        self,
        connection,
        lease,
        applied: AppliedRecovery,
        incoming: ExecutionObservation | None = None,
    ) -> ExecutionEventPayload:
        row = connection.execute(
            "SELECT event_kind,payload_json FROM task_execution_events WHERE task_kind=? "
            "AND task_id=? AND attempt=? AND lease_generation=? "
            "AND event_kind IN ('invocation_started','run_finished') "
            "ORDER BY event_id DESC LIMIT 1",
            (lease.task_kind, lease.task_id, lease.attempt, lease.generation),
        ).fetchone()
        observation = (
            ExecutionEventPayload.model_validate_json(row["payload_json"]).observation
            if row and row["event_kind"] == "run_finished"
            else None
            if row
            else ExecutionObservation(provider_attempt_count=0, usage_summary=UsageSummary())
        )
        if incoming is not None:
            if incoming.usage_summary is not None or observation is None:
                observation = incoming
            elif incoming.exception_type is not None:
                observation = observation.model_copy(
                    update={"exception_type": incoming.exception_type}
                )
        return ExecutionEventPayload(recovery=applied, observation=observation)

    @staticmethod
    def observation(result: AgentRunResult) -> ExecutionObservation:
        return ExecutionObservation(
            usage_summary=result.usage_summary,
            provider_attempt_count=result.provider_attempt_count,
            repair_count=result.repair_count,
            repairs=result.repair_observations,
        )

    def finished(self, lease: TaskLease, result: AgentRunResult, now: datetime) -> None:
        with self.database.transaction() as connection:
            now = utc_now()
            self.record(
                connection,
                lease,
                "run_finished",
                ExecutionEventPayload(
                    observation=ExecutionObservation(
                        usage_summary=result.usage_summary,
                        provider_attempt_count=result.provider_attempt_count,
                        repair_count=result.repair_count,
                        repairs=result.repair_observations,
                    )
                ),
                now,
                str(result.invocation_id),
            )
