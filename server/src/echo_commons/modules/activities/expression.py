import asyncio
import json
from uuid import UUID

from echo_commons.agents.contracts.activity import (
    ACTIVITY_EXPRESSION_CONTRACT,
    ActivityExpressionInput,
    ActivityExpressionProposal,
)
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import ActionSpace
from echo_commons.agents.contracts.invocation import (
    AgentInvocation,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    InvocationScope,
)
from echo_commons.agents.contracts.output import CheckedCharacterExpression
from echo_commons.agents.contracts.refs import ContextInputRef
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import LeaseLostError, with_heartbeat
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.execution.recovery import decide_run
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.activities.tasks.recovery import ActivityRecovery
from echo_commons.modules.social.contracts import ParticipationResult
from echo_commons.shared.actors import ActorRef


class ExpressionRecovery(ActivityRecovery):
    def apply(self, connection, lease, recovery, now, **kwargs):
        applied = super().apply(connection, lease, recovery, now, **kwargs)
        if applied and applied.task_state in ("failed", "cancelled"):
            self.expressions.finish_in(
                connection, self.tasks.get(connection, lease.task_id), applied.task_state, now
            )
        return applied


class ActivityExpression:
    def __init__(
        self,
        database,
        tasks,
        context,
        review,
        service,
        planner,
        sources,
        social,
        agents,
        outputs,
        limits,
        recorder,
    ):
        self.database, self.tasks, self.context, self.review = database, tasks, context, review
        self.service, self.planner, self.sources, self.social = service, planner, sources, social
        self.agents, self.outputs, self.limits, self.recorder = agents, outputs, limits, recorder
        self.queue = None
        self.heartbeat_seconds = 5

    def reconcile_in(self, connection, now):
        rows = connection.execute(
            "SELECT task_id FROM activity_expression_tasks WHERE status IN "
            "('pending','processing','retry_wait','suspended')"
        ).fetchall()
        for identity in rows:
            row = self.tasks.get(connection, identity[0])
            code = self.review.source_code(connection, row)
            if (
                not code
                and row["social_turn_id"]
                and not self.social.can_publish(connection, row["social_turn_id"])
            ):
                code = "source_replaced"
            if code:
                state = (
                    "suspended"
                    if code in ("community_paused", "character_unavailable")
                    else "cancelled"
                )
                if row["status"] != state:
                    self.tasks.release(connection, row["task_id"], state, now, now, code)
                    if state == "cancelled":
                        self.finish_in(connection, row, "cancelled", now)
                continue
            if row["status"] == "suspended":
                self.tasks.release(connection, row["task_id"], "pending", now, now)
            if row["social_turn_id"]:
                continue
            source = connection.execute(
                "SELECT * FROM activity_task_sources WHERE task_id=? AND "
                "status='pending_expression' ORDER BY created_at_utc,source_id LIMIT 1",
                (row["parent_task_id"],),
            ).fetchone()
            if source is None:
                conversation = self.planner.conversations.get(
                    connection, row["community_id"], row["conversation_id"]
                )
                member = self.planner.conversations.current(
                    connection, row["conversation_id"], ActorRef("character", row["character_id"])
                )
                original = self.context._restore(
                    self.context.inputs.get(
                        connection, row["community_id"], row["character_id"], row["input_id"]
                    )
                )
                audience = tuple(
                    m.membership_id
                    for m in self.planner.conversations.members(connection, row["conversation_id"])
                    if m.joined_at_utc <= original.prepared_at_utc
                )
                turn = self.planner.arrange_expression(
                    connection, conversation, member, now, audience
                )
                if turn is None:
                    continue
                source = connection.execute(
                    "SELECT * FROM activity_task_sources WHERE social_turn_id=? AND character_id=?",
                    (turn.social_turn_id, row["character_id"]),
                ).fetchone()
                connection.execute(
                    "UPDATE activity_task_sources SET task_id=?,status='attached' WHERE "
                    "source_id=?",
                    (row["parent_task_id"], source["source_id"]),
                )
                self.sources.finish(connection, row["parent_task_id"], "pending_expression", now)
            connection.execute(
                "UPDATE activity_expression_tasks SET social_turn_id=? WHERE task_id=?",
                (source["social_turn_id"], row["task_id"]),
            )

    def finish_in(self, connection, row, outcome, now, message=None):
        changed = connection.execute(
            "UPDATE activity_results SET publication_status=? WHERE result_id=? AND "
            "publication_status='pending'",
            (outcome, row["task_id"]),
        ).rowcount
        if not changed:
            return
        state = "completed" if outcome in ("published", "silent", "rejected") else outcome
        self.tasks.release(
            connection,
            row["task_id"],
            state,
            now,
            now,
            None if outcome in ("published", "silent") else row["last_error_code"] or outcome,
        )
        for source in connection.execute(
            "SELECT * FROM activity_task_sources WHERE task_id=? AND status='pending_expression'",
            (row["parent_task_id"],),
        ).fetchall():
            source_state = (
                "published"
                if message
                else "silent"
                if outcome == "silent"
                else "cancelled"
                if outcome == "cancelled"
                else "failed"
            )
            connection.execute(
                "UPDATE activity_task_sources SET status=?,updated_at_utc=? WHERE source_id=?",
                (source_state, utc_text(now), source["source_id"]),
            )
            self.social.expression_finished(
                connection,
                ParticipationResult(
                    source["social_turn_id"],
                    row["character_id"],
                    "completed"
                    if message or outcome == "silent"
                    else "cancelled"
                    if outcome == "cancelled"
                    else "failed",
                    "message"
                    if message
                    else "silent"
                    if outcome == "silent"
                    else "cancelled"
                    if outcome == "cancelled"
                    else "failed",
                    message,
                    source["membership_id"],
                    source["observation_max_sequence"],
                ),
                now,
            )
        lease = TaskLease(
            row["task_id"],
            "activity_expression",
            row["attempt_count"],
            row["lease_generation"],
            row["lease_owner"] or "lifecycle",
            now,
            row["trace_id"],
        )
        self.recorder.record(
            connection,
            lease,
            "completed" if state == "completed" else "lifecycle_changed",
            ExecutionEventPayload(reason_code=outcome, task_state=state),
            now,
        )

    def prepare(self, lease):
        with self.database.transaction() as connection:
            row = self.tasks.owned(connection, lease, utc_now())
            if row is None:
                raise LeaseLostError("Expression lease changed")
            if row["input_json"]:
                return ActivityExpressionInput.model_validate_json(row["input_json"])
            original = self.context._restore(
                self.context.inputs.get(
                    connection, row["community_id"], row["character_id"], row["input_id"]
                )
            )
            observed = self.context.observations.observe_in(
                connection,
                row["community_id"],
                row["character_id"],
                row["game_id"],
                participation_id=row["participation_id"],
            )
            working = self.context.working_memory.current_in(connection, original.scope)
            value = ActivityExpressionInput(
                snapshot_id=f"expression:{row['task_id']}",
                origin_input_id=original.snapshot_id,
                prepared_at_utc=utc_now(),
                scope=original.scope,
                source_versions=original.source_versions,
                action_space=ActionSpace(
                    output_contracts=(ACTIVITY_EXPRESSION_CONTRACT,),
                    tools=original.action_space.tools,
                ),
                material=original.material.model_copy(
                    update={
                        "working_memory": working,
                        "session_context": self.context.experiences.session_context(
                            connection,
                            row["community_id"],
                            row["character_id"],
                            observed.context,
                            utc_now(),
                        ),
                    }
                ),
                receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
                receipt_event_ids=tuple(json.loads(row["receipt_json"])["event_ids"])
                if row["receipt_json"]
                else (),
                current_observation={
                    "status": observed.context.game.status,
                    "state_version": observed.context.game.state_version,
                    "view": observed.view.model_dump(mode="json", exclude={"opportunities"})
                    if observed.view
                    else None,
                },
            )
            self.tasks.save_stage(
                connection, lease, "input_json", value.model_dump_json(), utc_now()
            )
            return value

    async def execute(self, lease):
        return await with_heartbeat(self.queue, lease, self._execute(lease), self.heartbeat_seconds)

    async def _execute(self, lease):
        with self.database.read() as connection:
            row = dict(self.tasks.get(connection, lease.task_id))
        saved_run = (
            self.outputs.restore_result(row["last_run_json"]) if row["last_run_json"] else None
        )
        if row["prepared_json"]:
            proposal = ActivityExpressionProposal.model_validate_json(row["prepared_json"])
            snapshot = await asyncio.to_thread(self.prepare, lease)
        elif row["expression_json"]:
            proposal = ActivityExpressionProposal(
                expression=CheckedCharacterExpression.model_validate_json(row["expression_json"])
            )
            snapshot = await asyncio.to_thread(self.prepare, lease)
        elif saved_run and saved_run.status in (
            AgentRunStatus.COMPLETED,
            AgentRunStatus.NO_PROPOSAL,
        ):
            proposal = (
                saved_run.output.payload if saved_run.output else ActivityExpressionProposal()
            )
            snapshot = await asyncio.to_thread(self.prepare, lease)
        else:
            snapshot = await asyncio.to_thread(self.prepare, lease)
            with self.database.read() as connection:
                agent = self.agents.resolve(
                    connection,
                    row["community_id"],
                    row["character_id"],
                    purpose=InvocationPurpose.ACTIVITY_EXPRESSION,
                )
            invocation = AgentInvocation(
                identity=InvocationIdentity(
                    agent_id=agent.descriptor.agent_id,
                    purpose=InvocationPurpose.ACTIVITY_EXPRESSION,
                    attempt=lease.attempt,
                ),
                scope=InvocationScope(
                    community_id=row["community_id"],
                    character_id=row["character_id"],
                    task_id=lease.task_id,
                    source_kind="activity_result",
                    source_id=lease.task_id,
                ),
                context=snapshot,
                context_input=ContextInputRef(
                    snapshot_id=snapshot.snapshot_id, snapshot_schema_version=1
                ),
                output_contract=ACTIVITY_EXPRESSION_CONTRACT,
                execution_policy=ExecutionPolicy(
                    allowed_tools=snapshot.action_space.tools,
                    model_profile=agent.descriptor.model_profile,
                    max_model_steps=self.limits.model_steps,
                    max_model_requests=self.limits.model_requests,
                    max_tool_calls=self.limits.tool_calls,
                    max_output_tokens=self.limits.max_output_tokens,
                    temperature=self.limits.temperature,
                    top_p=self.limits.top_p,
                    max_input_chars=self.context.policy.input_max_chars,
                    deadline_utc=lease.expires_at_utc,
                ),
                correlation=Correlation(task_id=lease.task_id, trace_id=UUID(lease.trace_id)),
            )
            self.save_stage(lease, "last_invocation_json", invocation.model_dump_json())
            self.recorder.started(lease, invocation, utc_now())
            result = await agent.run(invocation)
            self.recorder.finished(lease, result, utc_now())
            self.save_stage(lease, "last_run_json", result.model_dump_json())
            if recovery := decide_run(result):
                raise ExecutionError(
                    recovery.failure.code, recovery.failure.category, recovery.action
                )
            proposal = result.output.payload if result.output else ActivityExpressionProposal()
        self.save_stage(lease, "prepared_json", proposal.model_dump_json())
        await asyncio.to_thread(self.publish, lease, snapshot, proposal)
        return ExecutionOutcome(Disposition.HANDLED)

    def save_stage(self, lease, column, content):
        with self.database.transaction() as connection:
            self.tasks.save_stage(connection, lease, column, content, utc_now())

    def publish(self, lease, snapshot, proposal):
        with self.database.transaction() as connection:
            now = utc_now()
            row = self.tasks.owned(connection, lease, now)
            if row is None:
                raise LeaseLostError("Expression lease changed")
            if code := self.review.source_code(connection, row):
                self.queue.recovery.apply(connection, lease, self.queue.recovery.source(code), now)
                return
            if not self.social.can_publish(connection, row["social_turn_id"]):
                self.finish_in(connection, row, "cancelled", now)
                return
            if proposal.expression is None:
                self.finish_in(connection, row, "silent", now)
                return
            common = snapshot.material.conversation
            code = self.service.check(connection, common, proposal.expression.message)
            if code:
                self.finish_in(connection, row, "rejected", now)
                connection.execute(
                    "UPDATE activity_expression_tasks SET last_error_code=? WHERE task_id=?",
                    (code, row["task_id"]),
                )
                return
            turn = self.planner.social.by_id(connection, row["social_turn_id"])
            members = {
                m.membership_id
                for m in self.planner.conversations.members(connection, row["conversation_id"])
            }
            audience = tuple(sorted(set(turn.audience) & members))
            message, _ = self.service.save_in(
                connection,
                common,
                proposal.expression.message,
                activity_result_id=row["task_id"],
                turn_id=turn.social_turn_id,
                audience=audience,
                visibility=turn.visibility,
                trace_id=lease.trace_id,
                now=now,
            )
            if proposal.intents is not None:
                self.context.working_memory.expression_in(connection, snapshot, proposal.intents)
            self.finish_in(connection, row, "published", now, message)
            if proposal.comments_on_action:
                for event_id in snapshot.receipt_event_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_event_coverage VALUES (?,?)",
                        (row["task_id"], event_id),
                    )
