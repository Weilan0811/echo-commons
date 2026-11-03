import json
from zoneinfo import ZoneInfo

from echo_commons.agents.contracts.activity import (
    ACTIVITY_REPLY_CONTRACT,
    ACTIVITY_REPLY_SELECTION_CONTRACT,
    ActivityUnderstanding,
    IntentProposal,
    selection_contract,
    turn_contract,
)
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.activities.context import ActivityContext
from echo_commons.modules.activities.domain.task import task_view
from echo_commons.modules.activities.repositories.results import ActivityResults
from echo_commons.modules.activities.repositories.tasks import ActivityTasks
from echo_commons.modules.activities.tasks.recovery import ActivityRecovery
from echo_commons.modules.activities.tasks.review import ActivityReview
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.game_participation import GameParticipationService
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.shared.actors import ActorRef


class ActivityCommit:
    def __init__(
        self,
        database: Database,
        tasks: ActivityTasks,
        results: ActivityResults,
        context: ActivityContext,
        participation: GameParticipationService,
        outputs: OutputRegistry,
        review: ActivityReview,
        recovery: ActivityRecovery,
        thoughts: ThoughtRepository,
        communities: CommunityReader,
        sources,
    ) -> None:
        self.database, self.tasks, self.results, self.context = database, tasks, results, context
        self.communities = communities
        self.sources = sources
        self.expressions = None
        self.participation, self.outputs, self.review, self.recovery, self.thoughts = (
            participation,
            outputs,
            review,
            recovery,
            thoughts,
        )

    def commit(self, lease: TaskLease, artifact: dict) -> dict | None:
        with self.database.transaction() as connection:
            return self.commit_in(connection, lease, artifact)

    def commit_in(self, connection, lease, artifact):
        existing = self.results.for_task(connection, lease.task_id)
        if existing:
            return {
                "result_id": existing["result_id"],
                "receipt": json.loads(existing["receipt_json"])
                if existing["receipt_json"]
                else None,
            }
        now = utc_now()
        row = self.tasks.owned(connection, lease, now)
        if row is None:
            raise LeaseLostError("Activity result lease is no longer owned")
        if code := self.review.source_code(connection, row):
            self.recovery.apply(connection, lease, self.recovery.source(code), now)
            return None
        reply = row["purpose"] == "reply"
        view = task_view(row) if not reply else None
        opportunity = (
            next(o for o in view.opportunities if o.opportunity_id == row["opportunity_id"])
            if view
            else None
        )
        expression, expression_status, thought = None, "silent", ""
        if artifact["mode"] == "automatic":
            if row["mode"] != "automatic" or len(opportunity.legal_actions) != 1:
                raise ValueError("Automatic action requires exactly one legal action")
            action = opportunity.legal_actions[0]
        else:
            if row["prepared_json"] is None or artifact != json.loads(row["prepared_json"]):
                raise ValueError("Activity commit requires the complete saved task result")
            snapshot = self.context._restore(
                self.context.inputs.get(
                    connection, row["community_id"], row["character_id"], row["input_id"]
                )
            )
            result = self.outputs.restore_result(json.dumps(artifact["run"]))
            if result.agent_id != f"character:{row['community_id']}:{row['character_id']}":
                raise ValueError("Activity result belongs to another character")
            expected_contract = (
                (
                    ACTIVITY_REPLY_SELECTION_CONTRACT
                    if artifact["mode"] == "decision"
                    else ACTIVITY_REPLY_CONTRACT
                )
                if reply
                else (
                    selection_contract(view.game_type)
                    if artifact["mode"] == "decision"
                    else turn_contract(view.game_type)
                )
            )
            if result.output is None or result.output.contract != expected_contract:
                raise ValueError("Activity result has an unrelated output contract")
            proposal = result.output.payload
            self.review.proposal(row, proposal, snapshot)
            action = proposal.action if not reply else None
            if artifact["mode"] == "decision":
                retained = set(proposal.retained_intent_ids)
                intents = tuple(
                    IntentProposal(content=i.content, message_ids=i.message_ids)
                    for i in snapshot.material.working_memory.intents
                    if i.intent_id in retained
                )
                if proposal.expression_needed:
                    expression_status = "pending_generation"
                # 选项接口没有逐条消息含义，未形成理解结果的聊天继续保持待处理。
                if not snapshot.material.conversation.perspective.trigger_message_ids:
                    self.context.record_understanding_in(
                        connection,
                        row["community_id"],
                        row["character_id"],
                        row["input_id"],
                        ActivityUnderstanding(
                            messages=(),
                            event_ids=tuple(e.event_id for e in snapshot.material.game.events),
                        ),
                    )
            else:
                intents = proposal.intents
                thought = proposal.understanding.thought
                self.context.record_understanding_in(
                    connection,
                    row["community_id"],
                    row["character_id"],
                    row["input_id"],
                    proposal.understanding,
                )
                expression = proposal.expression
                if expression:
                    expression_status = "pending_review"
            self.context.working_memory.replace_in(
                connection,
                row["community_id"],
                row["character_id"],
                row["input_id"],
                expected_version=snapshot.material.working_memory.version,
                intents=intents,
            )
        receipt = None
        if not reply:
            actor = ActorRef("character", row["character_id"])
            access = self.context.observations.participation.participant_context(
                connection, row["community_id"], actor, row["game_id"], row["participation_id"]
            ).access
            definition = self.tasks.definition(row, self.participation.games)
            command = definition.models.action_command(
                request_id=row["request_id"],
                opportunity_id=row["opportunity_id"],
                expected_state_version=row["state_version"],
                action=action,
            )
            receipt = self.participation.games.submit_action(connection, access, command)
        identity = self.results.add(
            connection, lease.task_id, artifact, receipt, expression, expression_status, now
        )
        if expression_status != "silent" and self.expressions:
            self.expressions.tasks.enqueue(connection, identity, now)
        if artifact["mode"] != "automatic":
            covered = set(snapshot.material.reaction_event_ids)
            if expression:
                covered.update(
                    ref.removeprefix("game_event:")
                    for claim in expression.claims
                    for ref in claim.evidence_refs
                    if ref.startswith("game_event:")
                )
            for event_id in covered:
                connection.execute(
                    "INSERT OR IGNORE INTO activity_event_coverage VALUES (?,?)",
                    (identity, event_id),
                )
        if (
            receipt
            and expression_status != "silent"
            and artifact["mode"] not in ("automatic", "decision")
            and proposal.comments_on_action
        ):
            for event_id in receipt.event_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO activity_event_coverage VALUES (?,?)",
                    (identity, event_id),
                )
        if thought.strip():
            community = self.communities.get(connection, row["community_id"])
            self.thoughts.add_activity(
                connection,
                identity,
                row["community_id"],
                row["character_id"],
                row["conversation_id"],
                community.world_time_utc.astimezone(ZoneInfo(community.timezone))
                .date()
                .isoformat(),
                thought,
                now,
            )
        self.tasks.release(connection, lease.task_id, "completed", now, now)
        if artifact["mode"] == "automatic":
            self.sources.requeue(connection, lease.task_id, now)
        else:
            self.sources.finish(
                connection,
                lease.task_id,
                "silent" if expression_status == "silent" else "pending_expression",
                now,
            )
        self.recovery.recorder.record(
            connection,
            lease,
            "completed",
            ExecutionEventPayload(
                reason_code="reply_decided" if reply else "action_committed", task_state="completed"
            ),
            now,
        )
        return {
            "result_id": identity,
            "receipt": receipt.model_dump(mode="json") if receipt else None,
        }
