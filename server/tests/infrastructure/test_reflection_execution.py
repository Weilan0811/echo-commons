import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from support.application import settings_for
from support.reflection import seed

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.agents.harness.output import OutputContentTooLong, check_content_length
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.lease import LeaseLostError, with_heartbeat
from echo_commons.execution.recovery import decision
from echo_commons.infrastructure.models.openai_compatible import _request_params
from echo_commons.infrastructure.models.protocol import ModelRequest
from echo_commons.modules.reflection.contracts.candidates import SegmentSummaryModelAction
from echo_commons.modules.reflection.domain.graph import (
    ReflectionArtifact,
)


@pytest.mark.parametrize(("field", "limit"), [("summary", 160), ("content", 240), ("content", 320)])
def test_summary_body_limit_counts_punctuation_without_counting_follow_up(field, limit):
    body = {field: "记" * (limit - 2) + "。\n", "follow_up": {"reason": "依据" * 500}}
    check_content_length(body, limit)
    body[field] += "。"
    with pytest.raises(OutputContentTooLong) as error:
        check_content_length(body, limit)
    assert f"实际 {limit + 1}" in error.value.repair_hint
    assert f"上限 {limit}" in error.value.repair_hint


def test_prepared_reflection_uses_original_snapshot_and_current_lease(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as application:
            seed(application)
            lease = await application.reflection_queue.claim("reflection-worker", datetime.now(UTC))
            first = application.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            second = application.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            assert first.invocation.context == second.invocation.context
            assert (
                first.invocation.context.scope.character_id == first.invocation.scope.character_id
            )
            assert first.invocation.execution_policy.model_profile == "light"
            assert first.invocation.execution_policy.thinking is True
            assert first.invocation.execution_policy.max_output_tokens >= 8192
            assert "最多 160" in first.invocation.execution_policy.output_instructions
            assert first.invocation.execution_policy.max_content_chars == 160
            invocation = first.invocation
            entry = application.gateway.registry.resolve("light")
            request = ModelRequest(
                invocation_id=invocation.identity.invocation_id,
                trace_id=invocation.correlation.trace_id,
                agent_id=invocation.identity.agent_id,
                model_profile="light",
                attempt=1,
                step_index=1,
                output_contract=invocation.output_contract,
                thinking=invocation.execution_policy.thinking,
                reasoning_effort=invocation.execution_policy.reasoning_effort,
                max_thinking_tokens=invocation.execution_policy.max_thinking_tokens,
            )
            params = _request_params(entry, request)
            assert params["extra_body"]["thinking"] == {"type": "enabled"}
            assert "temperature" not in params
            ordinary = _request_params(
                entry, request.model_copy(update={"thinking": None, "reasoning_effort": None})
            )
            assert ordinary["extra_body"] == dict(entry.extra_body)
            assert application.gateway._clients == {}
            assert await application.reflection_queue.apply_recovery(
                lease,
                datetime.now(UTC),
                decision("execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL),
            )
            with pytest.raises(LeaseLostError):
                await first.agent.run(first.invocation)
            assert application.gateway._clients == {}

    asyncio.run(run())


@pytest.mark.model
def test_two_characters_reflect_real_private_materials(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as application:
            seed(application)
            leases = tuple(
                [
                    await application.reflection_queue.claim(
                        f"reflection-{index}", datetime.now(UTC)
                    )
                    for index in range(2)
                ]
            )
            prepared = tuple(
                application.reflection_execution.prepare(
                    lease.task_id,
                    attempt=lease.attempt,
                    deadline_utc=datetime.now(UTC) + timedelta(seconds=300),
                )
                for lease in leases
            )
            results = await asyncio.gather(
                *(
                    with_heartbeat(
                        application.reflection_queue, lease, item.agent.run(item.invocation), 10
                    )
                    for lease, item in zip(leases, prepared, strict=True)
                )
            )
            assert {item.invocation.scope.character_id for item in prepared} == {"first", "second"}
            for lease, item, result in zip(leases, prepared, results, strict=True):
                assert result.status is AgentRunStatus.COMPLETED
                assert result.model_profile == "light"
                assert isinstance(result.output.payload, SegmentSummaryModelAction)
                character = item.invocation.scope.character_id
                own, other = (
                    ("草莓417", "香蕉918") if character == "first" else ("香蕉918", "草莓417")
                )
                serialized = item.invocation.context.model_dump_json()
                assert own in serialized and other not in serialized
                assert other not in result.output.payload.summary
                assert result.usage_summary.model_request_count >= 1
                again = application.reflection_execution.prepare(
                    lease.task_id, attempt=lease.attempt
                )
                assert again.invocation.context == item.invocation.context
                artifact = application.reflection_commit.commit(
                    lease, item.invocation, result, datetime.now(UTC)
                )
                assert isinstance(artifact, ReflectionArtifact)
                assert artifact == application.reflection_commit.commit(
                    lease, item.invocation, result, datetime.now(UTC)
                )
                with application.database.read() as connection:
                    nodes = application.reflection_queue.nodes.for_graph(
                        connection, str(artifact.graph_run_id)
                    )
                    node = next(node for node in nodes if node.task_id == artifact.node_task_id)
                    assert node.status == "completed" and node.artifact_id == artifact.artifact_id
                    for child in nodes:
                        if child.node_key in ("relationship_reflect", "state_reflect"):
                            assert child.status == "skipped" or child.input_artifact_refs == (
                                artifact.reference,
                            )

    asyncio.run(run())
