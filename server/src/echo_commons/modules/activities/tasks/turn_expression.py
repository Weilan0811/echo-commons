import asyncio
import json
from contextlib import nullcontext
from functools import partial

from echo_commons.agents.contracts.activity import (
    ACTIVITY_EXPRESSION_CONTRACT,
    ActivityExpressionInput,
    ActivityExpressionProposal,
    ExpressionOrigin,
    TurnExpressionStage,
)
from echo_commons.agents.contracts.input import ActionSpace
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.execution.clock import utc_now
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.infrastructure.database.mapping import utc_text


class TurnExpressionPreparation:
    def __init__(self, execution, expressions):
        self.execution, self.expressions = execution, expressions
        self.database, self.context = execution.database, execution.context

    def snapshot(self, original, decision, task_id, *, generate):
        common = original.material.conversation
        if generate:
            common = common.model_copy(
                update={
                    "memory": common.memory.model_copy(
                        update={
                            "context_prepared": False,
                            "input_budget": self.context.input_budgets["expression"].model_copy(
                                update={
                                    "max_chars": min(
                                        self.context.policy.input_max_chars,
                                        self.context.input_budgets["expression"].max_chars,
                                    )
                                }
                            ),
                        }
                    )
                }
            )
        game = original.material.game
        return ActivityExpressionInput(
            snapshot_id=f"turn-expression:{task_id}",
            phase="before_action",
            origin_input_id=original.snapshot_id,
            prepared_at_utc=utc_now(),
            scope=original.scope,
            source_versions=original.source_versions,
            action_space=ActionSpace(
                output_contracts=(ACTIVITY_EXPRESSION_CONTRACT,), tools=original.action_space.tools
            ),
            material=original.material.model_copy(
                update={
                    "conversation": common,
                    "game": game.model_copy(
                        update={"view": game.view.model_copy(update={"opportunities": ()})}
                    ),
                }
            ),
            origin=ExpressionOrigin(
                input_id=original.snapshot_id,
                prepared_at_utc=original.prepared_at_utc,
                state_version=game.state_version,
                message_upper_sequence=game.through_message_sequence,
                message_ids=common.perspective.trigger_message_ids,
                event_ids=tuple(e.event_id for e in game.events),
                source_versions=original.source_versions,
                decision=decision,
            ),
            receipt=None,
            current_observation={
                "status": game.status,
                "state_version": game.state_version,
                "view": game.view.model_dump(mode="json", exclude={"opportunities"}),
            },
        )

    def save(self, lease, artifact, stage):
        artifact["turn_expression"] = stage.model_dump(mode="json")
        self.execution._stage(lease, "prepared_json", json.dumps(artifact, ensure_ascii=False))

    def save_generation(self, artifact, lease, column, serialized):
        stage = TurnExpressionStage.model_validate(artifact["turn_expression"])
        field = {"last_invocation_json": "invocation", "last_run_json": "run"}[column]
        updated = stage.model_copy(update={field: json.loads(serialized)})
        artifact["turn_expression"] = updated.model_dump(mode="json")
        self.execution._stage(lease, "prepared_json", json.dumps(artifact, ensure_ascii=False))

    async def prepare(self, lease, artifact):
        row = await asyncio.to_thread(self.execution._load, lease)
        if row["purpose"] != "turn":
            return artifact
        stage = TurnExpressionStage.model_validate(artifact.get("turn_expression", {}))
        if stage.proposal is not None:
            return artifact
        if artifact["mode"] == "automatic":
            stage = stage.model_copy(update={"proposal": ActivityExpressionProposal()})
        else:
            original = await asyncio.to_thread(
                self.context.restore, row["community_id"], row["character_id"], row["input_id"]
            )
            proposal = self.execution.outputs.restore_result(
                json.dumps(artifact["run"])
            ).output.payload
            generate = artifact["mode"] == "decision" and proposal.expression_needed
            body = getattr(proposal, "expression", None)
            if generate:
                saved = (
                    self.execution.outputs.restore_result(json.dumps(stage.run))
                    if stage.run
                    else None
                )
                complete = saved and saved.status in (
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.NO_PROPOSAL,
                )
                async with (
                    self.expressions.model_budget.reservation(priority=1)
                    if not complete
                    else nullcontext()
                ):
                    if stage.input is None:
                        stage = stage.model_copy(
                            update={
                                "input": self.snapshot(
                                    original,
                                    artifact.get("decision")
                                    or artifact["run"]["output"]["payload"],
                                    row["task_id"],
                                    generate=True,
                                )
                            }
                        )
                    with self.database.transaction() as connection:
                        value = self.expressions._complete_input_in(connection, stage.input)
                    stage = stage.model_copy(update={"input": value})
                    await asyncio.to_thread(self.save, lease, artifact, stage)
                    if not value.material.conversation.memory.context_prepared:
                        raise ExecutionDeferred("memory_summary_pending")
                    if complete:
                        result = saved
                    else:
                        result = await self.expressions.generate(
                            lease, row, value, partial(self.save_generation, artifact)
                        )
                    stage = TurnExpressionStage.model_validate(artifact["turn_expression"])
                    stage = stage.model_copy(
                        update={
                            "proposal": result.output.payload
                            if result.output
                            else ActivityExpressionProposal()
                        }
                    )
            else:
                stage = stage.model_copy(
                    update={
                        "input": self.snapshot(
                            original,
                            artifact.get("decision") or artifact["run"]["output"]["payload"],
                            row["task_id"],
                            generate=False,
                        )
                        if body
                        else None,
                        "proposal": ActivityExpressionProposal(
                            expression=body,
                            comments_on_action=getattr(proposal, "comments_on_action", False),
                        ),
                    }
                )
        await asyncio.to_thread(self.save, lease, artifact, stage)
        return artifact

    def prepare_waiting(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM activity_tasks WHERE status IN ('pending','retry_wait') AND "
                "json_extract(prepared_json,"
                "'$.turn_expression.input.material.conversation.memory.context_prepared')=0 "
                "ORDER BY updated_at_utc,task_id"
            ).fetchall()
            for row in rows:
                if self.execution.review.source_code(connection, row):
                    continue
                artifact = json.loads(row["prepared_json"])
                stage = TurnExpressionStage.model_validate(artifact["turn_expression"])
                value = self.expressions._complete_input_in(connection, stage.input)
                artifact["turn_expression"] = stage.model_copy(update={"input": value}).model_dump(
                    mode="json"
                )
                connection.execute(
                    "UPDATE activity_tasks SET prepared_json=?,available_at_utc=? WHERE task_id=?",
                    (json.dumps(artifact, ensure_ascii=False), utc_text(utc_now()), row["task_id"]),
                )
                return value.material.conversation.memory.context_prepared
        return False
