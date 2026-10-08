import asyncio
import shutil
import socket
from dataclasses import replace
from datetime import timedelta
from importlib.resources import files
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient
from historical_database import copy_to_historical_schema
from test_application_lifecycle import settings_for
from test_final_acceptance import create_conversation
from test_reflection_execution import seed
from test_reflection_queue import prepare_queue
from test_social_planning import build_planning_system, send
from test_task_queue import queue_system

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.execution.recovery import QueuePolicy, RecoveryPolicy, decision
from echo_commons.execution.registry import TaskRegistry
from echo_commons.infrastructure.database.execution_records import ExecutionRecordRepository
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.shared.management import PageOptions


def payloads(database, kind="recovery_applied"):
    with database.read() as connection:
        return [
            ExecutionEventPayload.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM task_execution_events WHERE event_kind=? "
                "ORDER BY event_id",
                (kind,),
            )
        ]


def test_policy_preserves_failure_wait_and_exhaustion():
    policy = RecoveryPolicy(QueuePolicy(max_attempts=2, retry_backoff_seconds=3))
    recovery = decision("rate_limit", FailureCategory.PROVIDER, RecoveryAction.RETRY_TASK, wait=12)
    now = utc_now()
    first = policy.plan(recovery, 1, now)
    assert first.effective_wait_seconds == 12
    assert first.next_attempt_at_utc == now + timedelta(seconds=12)
    exhausted = policy.plan(recovery, 2, now)
    assert exhausted.retry_exhausted and exhausted.action is RecoveryAction.FAIL
    assert exhausted.decision == recovery and exhausted.next_attempt_at_utc is None
    deferred = policy.plan(
        decision("community_paused", FailureCategory.SOURCE, RecoveryAction.DEFER), 5, now
    )
    assert not deferred.retry_exhausted and deferred.task_state == "retry_wait"
    unhandled = policy.plan(
        decision("invalid_model_output", FailureCategory.MODEL_OUTPUT, RecoveryAction.REPAIR),
        1,
        now,
    )
    assert unhandled.decision.failure.code == "agent_run_state_invalid"
    provider = policy.classify(ModelGatewayError(code="connection_error", provider_attempt=2))
    assert provider.failure.category is FailureCategory.PROVIDER
    assert policy.classify(ValueError("private text")).failure.code == "execution_unexpected_error"


def test_review_hint_is_replaced_by_network_failure_and_exhaustion(tmp_path):
    system = queue_system(tmp_path, QueuePolicy(max_attempts=2, retry_backoff_seconds=0))

    async def run():
        lease = await system.queue.claim("review", utc_now())
        await system.queue.claim("other-character", utc_now())
        review = system.queue.recovery.review("utterance_too_long")
        applied = await system.queue.apply_recovery(lease, utc_now(), review)
        assert applied.action is RecoveryAction.RETRY_TASK
        with system.database.read() as connection:
            assert "utterance_too_long" in system.queue.recovery.hint(connection, lease.task_id)
            original = system.tasks.get(connection, lease.task_id)["snapshot_json"]
        next_lease = await system.queue.claim("network", utc_now())
        assert next_lease.task_id == lease.task_id
        network = decision("connection_error", FailureCategory.PROVIDER, RecoveryAction.RETRY_TASK)
        applied = await system.queue.apply_recovery(next_lease, utc_now(), network)
        assert applied.retry_exhausted and applied.decision.failure.code == "connection_error"
        with system.database.read() as connection:
            assert system.queue.recovery.hint(connection, lease.task_id) is None
            assert system.tasks.get(connection, lease.task_id)["snapshot_json"] == original
            page = ExecutionRecordRepository().history(
                connection,
                "conversation_reply",
                lease.task_id,
                "community",
                "first"
                if system.tasks.get(connection, lease.task_id)["character_id"] == "first"
                else "second",
                PageOptions(limit=1),
            )
            assert page["has_more"] and page["cursor"]
            with pytest.raises(ValueError, match="different query"):
                ExecutionRecordRepository().history(
                    connection,
                    "conversation_reply",
                    "another",
                    "community",
                    "first",
                    PageOptions(cursor=page["cursor"]),
                )

    asyncio.run(run())
    assert len(payloads(system.database)) == 2


def test_version_two_migration_preserves_real_tasks(tmp_path):
    sql = tmp_path / "version-two"
    sql.mkdir()
    for name in ("0001_initial.sql", "0002_social_turn_states.sql"):
        source = files("echo_commons.infrastructure.database.sql").joinpath(name)
        shutil.copyfile(str(source), sql / name)
    system = build_planning_system(tmp_path)
    send(system)
    system.planner.plan()
    database = copy_to_historical_schema(system.database, sql, tmp_path / "historical.sqlite3")
    with database.read() as connection:
        before = [
            tuple(row)
            for row in connection.execute("SELECT * FROM conversation_tasks ORDER BY task_id")
        ]
    assert initialize(database) == initialize(database) == 9
    with database.read() as connection:
        assert before == [
            tuple(row)
            for row in connection.execute("SELECT * FROM conversation_tasks ORDER BY task_id")
        ]
        assert connection.execute("SELECT COUNT(*) FROM task_execution_events").fetchone()[0] == 0
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_valid_reflection_lease_defers_without_failing_graph(tmp_path):
    system, _, _, queue = prepare_queue(tmp_path, max_attempts=1)

    async def run():
        lease = await queue.claim("pause", utc_now())
        system.communities.update("community", expected_version=1, status=CommunityStatus.PAUSED)
        with pytest.raises(ExecutionDeferred):
            await queue.renew(lease, utc_now())
        applied = await queue.apply_recovery(
            lease, utc_now(), queue.recovery.classify(ExecutionDeferred())
        )
        assert applied.action is RecoveryAction.DEFER and not applied.retry_exhausted
        with system.database.read() as connection:
            node = queue.nodes.get(connection, lease.task_id)
            assert node.status == "retry_wait" and node.lease is None
            assert queue.run_for(connection, node).status == "running"
        assert await queue.claim("paused", utc_now()) is None
        system.communities.update("community", expected_version=2, status=CommunityStatus.ACTIVE)
        assert await queue.claim("resumed", utc_now()) is not None

    asyncio.run(run())


def test_unknown_handler_has_configuration_reason_and_zero_requests(tmp_path):
    system = queue_system(tmp_path, QueuePolicy(retry_backoff_seconds=0))
    asyncio.run(TaskDispatcher(system.queue, TaskRegistry(), "unknown-handler").dispatch_once())
    payload = payloads(system.database)[0]
    assert payload.observation.usage_summary.model_request_count == 0
    assert payload.observation.provider_attempt_count == 0
    applied = payload.recovery
    assert applied.decision.failure.code == "task_handler_not_registered"
    assert applied.decision.failure.category is FailureCategory.CONFIGURATION


@pytest.mark.parametrize("failure", ["binding", "snapshot"])
def test_real_preparation_failure_keeps_reason_and_zero_requests(tmp_path, failure):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as application:
            create_conversation(application)
            if failure == "binding":
                application.handler.execution.agents.bindings = MappingProxyType({})
                expected = "agent_binding_invalid"
            else:
                with application.database.transaction() as connection:
                    player = connection.execute(
                        "SELECT membership_id FROM conversation_memberships "
                        "WHERE actor_kind='player' AND conversation_id='conversation'"
                    ).fetchone()[0]
                    connection.execute("UPDATE conversation_tasks SET membership_id=?", (player,))
                expected = "task_snapshot_identity_mismatch"
            dispatcher = application.supervisor.workers["conversations-0"].dispatcher
            assert await dispatcher.dispatch_once()
            payload = payloads(application.database)[0]
            assert payload.recovery.decision.failure.code == expected
            assert payload.observation.usage_summary.model_request_count == 0
            assert payload.observation.provider_attempt_count == 0
            assert application.gateway._clients == {}

    asyncio.run(run())


def test_capture_disabled_history_is_scoped_and_paged(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        application = client.app.state.application
        create_conversation(application)
        lease = asyncio.run(application.queue.claim("review", utc_now()))
        asyncio.run(
            application.queue.apply_recovery(
                lease, utc_now(), application.queue.recovery.review("thought_too_long")
            )
        )
        with application.database.read() as connection:
            character = connection.execute(
                "SELECT character_id FROM conversation_tasks WHERE task_id=?", (lease.task_id,)
            ).fetchone()[0]
        url = f"/internal/characters/{character}/tasks/{lease.task_id}"
        response = client.get(url, params={"community_id": "community", "limit": 1})
        assert response.status_code == 200, response.text
        history = response.json()["recovery_history"]
        assert history["has_more"] and history["cursor"]
        second = client.get(url, params={"community_id": "community", "cursor": history["cursor"]})
        assert (
            second.json()["recovery_history"]["items"][0]["payload"]["recovery"]["decision"][
                "failure"
            ]["code"]
            == "thought_too_long"
        )
        assert client.get(url, params={"community_id": "another"}).status_code == 404
        logs = (tmp_path / "logs/echo.log").read_text(encoding="utf-8")
        assert "请缩短" not in logs


@pytest.mark.model
def test_real_network_attempts_are_counted_without_task_repair(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"retry_backoff_seconds": 0, "max_agent_attempts": 2}
    )

    async def run():
        async with application_lifecycle(settings) as application:
            create_conversation(application)
            lease = await application.queue.claim("network", utc_now())
            await application.queue.claim("other-character", utc_now())
            prepared = application.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
            # 真实绑定端口且不监听，系统拒绝连接；没有服务或预设响应。
            with socket.socket() as closed_endpoint:
                closed_endpoint.bind(("127.0.0.1", 0))
                port = closed_endpoint.getsockname()[1]
                registry = application.models
                entries = {
                    key: replace(
                        value,
                        base_url=f"http://127.0.0.1:{port}",
                        request_timeout_seconds=2,
                        max_retries=1,
                        retry_backoff_seconds=0,
                    )
                    for key, value in registry.entries.items()
                }
                gateway = OpenAICompatibleGateway(replace(registry, entries=entries))
                prepared.agent.backend._loop.gateway = gateway
                try:
                    for attempt in (1, 2):
                        outcome = await application.handler.execute(lease)
                        assert outcome.disposition is Disposition.RECOVERY_REQUIRED
                        assert outcome.observation.usage_summary.model_request_count == 1
                        assert outcome.observation.provider_attempt_count == 2
                        assert outcome.recovery.failure.category is FailureCategory.PROVIDER
                        assert outcome.recovery.failure.repair_hint is None
                        applied = await application.queue.apply_recovery(
                            lease, utc_now(), outcome.recovery, outcome.observation
                        )
                        assert applied.retry_exhausted == (attempt == 2)
                        if attempt == 1:
                            lease = await application.queue.claim("retry-network", utc_now())
                            retry = application.handler.execution.prepare(
                                lease.task_id, attempt=lease.attempt
                            )
                            assert retry.invocation.execution_policy.repair_hint is None
                finally:
                    await gateway.close()

    asyncio.run(run())


@pytest.mark.model
@pytest.mark.parametrize("kind", ["conversation", "reflection"])
def test_real_review_rejection_next_invocation_preserves_input_and_hint(tmp_path, kind):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"retry_backoff_seconds": 0, "max_agent_attempts": 2}
    )

    async def run():
        async with application_lifecycle(settings) as application:
            if kind == "conversation":
                create_conversation(application)
                queue, handler = application.queue, application.handler
                # 审核限制采用合法小值，固定业务提示保持原正文。
                handler.commit.review.policy = replace(
                    handler.commit.review.policy, max_utterance_chars=1
                )
            else:
                seed(application)
                queue = application.reflection_queue
                handler = application.supervisor.workers[
                    "reflection-0"
                ].dispatcher.registry.resolve("reflection")
                handler.commit.review = replace(handler.commit.review, max_output_chars=1)
            lease = await queue.claim("first", utc_now())
            await queue.claim("other-character", utc_now())
            first = handler.execution.prepare(lease.task_id, attempt=lease.attempt)
            original = first.invocation.context.model_dump_json()
            outcome = await handler.execute(lease)
            assert outcome.disposition is Disposition.HANDLED
            next_lease = await queue.claim("second", utc_now())
            assert next_lease.task_id == lease.task_id
            second = handler.execution.prepare(next_lease.task_id, attempt=next_lease.attempt)
            assert second.invocation.context.model_dump_json() == original
            assert (
                second.invocation.identity.invocation_id != first.invocation.identity.invocation_id
            )
            assert "上一轮输出未通过校验" in second.invocation.execution_policy.repair_hint
            await handler.execute(next_lease)
            starts = payloads(application.database, "invocation_started")
            assert starts[-1].repair_hint_used == second.invocation.execution_policy.repair_hint
            assert payloads(application.database)[-1].recovery.retry_exhausted

    asyncio.run(run())
