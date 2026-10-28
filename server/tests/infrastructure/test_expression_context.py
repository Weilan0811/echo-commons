import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from support.application import settings_for
from support.http import create_group
from support.social import build_planning_system

from echo_commons.agents.contracts.context import EnvironmentContext
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_EXPRESSION_TYPE,
    CheckedCharacterExpression,
    OutputRegistry,
)
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.app.composition import assemble
from echo_commons.app.main import create_app
from echo_commons.modules.conversations.export import ConversationExport
from echo_commons.modules.conversations.management import inspected_result
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.shared.errors import ConflictError


@pytest.fixture
def expression_loop():
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture
def expression_app(tmp_path, expression_loop):
    system = build_planning_system(tmp_path)
    app = assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(system.database.path)}
        )
    )
    yield app
    expression_loop.run(app.gateway.close())


def initiate(app, *, request_id="context", situation="你想邀请大家明天一起线上聊天。"):
    return app.conversation_initiations.request(
        "community", "conversation", "first", situation, request_id=request_id
    )


def test_expression_references_and_types_use_the_actual_frozen_input(expression_app):
    app = expression_app
    task = initiate(app)
    invocation = app.handler.execution.prepare(task, attempt=1).invocation
    assert invocation.output_contract == CHARACTER_EXPRESSION_CONTRACT
    registry = OutputRegistry()
    registry.register(CHARACTER_EXPRESSION_CONTRACT, CHARACTER_EXPRESSION_TYPE)
    prompt = project_snapshot(
        invocation.context, output_contract=invocation.output_contract, outputs=registry
    )
    payload = {
        "claims": [
            {
                "claim": "我是当前资料里的角色",
                "status": "supported",
                "evidence_refs": ["identity:profile"],
                "reason": "人物资料提供身份。",
            }
        ],
        "message": {"thought": "", "utterance": "明天一起聊聊吧。", "reply_to": None},
    }
    parsed = registry.parse(invocation.output_contract, payload, evidence_refs=prompt.evidence_refs)
    assert isinstance(parsed, CheckedCharacterExpression)
    payload["claims"][0]["evidence_refs"] = ["memory_fact:not-provided"]
    with pytest.raises(ValidationError):
        registry.parse(invocation.output_contract, payload, evidence_refs=prompt.evidence_refs)
    payload["claims"][0]["evidence_refs"] = []
    with pytest.raises(ValidationError):
        registry.parse(invocation.output_contract, payload, evidence_refs=prompt.evidence_refs)


def test_world_edit_does_not_change_an_existing_frozen_task(expression_app):
    app = expression_app
    initial = app.community_management.community("community")
    app.communities.update(
        "community",
        expected_version=initial.state_version,
        player_id="alice",
        world_description="这是一座学园都市。",
        community_rules="成员通过屏幕交流。",
    )
    task = initiate(app)
    original = app.handler.execution.prepare(task, attempt=1).invocation.context
    assert original.environment.world_description == "这是一座学园都市。"
    assert original.environment.community_rules == "成员通过屏幕交流。"
    community = app.community_management.community("community")
    updated = app.communities.update(
        "community",
        expected_version=community.state_version,
        player_id="alice",
        world_description="都市中的学校共同自治。",
        community_rules="成员通过线上群聊交流。",
    )
    assert updated.state_version == community.state_version + 1
    assert original.environment.community_version == community.state_version
    assert app.handler.execution.prepare(task, attempt=1).invocation.context == original
    with pytest.raises(ConflictError):
        app.communities.update(
            "community",
            expected_version=community.state_version,
            player_id="alice",
            world_description="过期更新",
        )
    with app.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_community_context_api_requires_membership_and_version(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        current = client.get("/api/communities/community", params={"player_id": "alice"}).json()
        assert current["world_description"] == current["community_rules"] == ""
        body = {
            "player_id": "alice",
            "expected_version": current["state_version"],
            "world_description": "学园都市",
            "community_rules": "通过屏幕交流",
        }
        response = client.patch("/api/communities/community/context", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["world_description"] == "学园都市"
        assert client.patch("/api/communities/community/context", json=body).status_code == 409
        client.post("/api/players", json={"player_id": "outsider", "display_name": "访客"})
        body.update(player_id="outsider", expected_version=response.json()["state_version"])
        assert client.patch("/api/communities/community/context", json=body).status_code == 404


def test_legacy_environment_serialization_preserves_existing_fields():
    old = {
        "world_time_utc": "2026-10-27T00:00:00Z",
        "community_status": "active",
        "conversation_kind": "group",
    }
    restored = EnvironmentContext.model_validate(old)
    assert restored.model_dump(mode="json") == old
    assert restored.timezone == "UTC" and restored.world_description == ""


def test_input_budget_stops_before_a_model_request(expression_app, expression_loop):
    app = expression_app
    task = initiate(app)
    lease = expression_loop.run(app.queue.claim("budget-verification", datetime.now(UTC)))
    assert lease is not None and lease.task_id == task
    prepared = app.handler.execution.prepare(task, attempt=lease.attempt)
    invocation = prepared.invocation.model_copy(
        update={
            "execution_policy": prepared.invocation.execution_policy.model_copy(
                update={"max_input_chars": 1}
            )
        }
    )
    result = expression_loop.run(prepared.agent.run(invocation))
    assert result.status is AgentRunStatus.FAILED
    assert result.diagnostic_codes == ("input_budget_exhausted",)
    assert result.usage_summary.model_request_count == 0


@pytest.mark.model
def test_real_native_search_and_private_claims_publish_only_message(
    expression_app, expression_loop, tmp_path
):
    async def run():
        app = expression_app
        task = initiate(app, situation="老师问起你昨天是否替他向朋友借过相机。你想先回想，再回复。")
        lease = await app.queue.claim("expression-verification", datetime.now(UTC))
        assert lease is not None and lease.task_id == task
        prepared = app.handler.execution.prepare(
            task, attempt=lease.attempt, deadline_utc=datetime.now(UTC) + timedelta(seconds=75)
        )
        invocation = prepared.invocation.model_copy(
            update={
                "execution_policy": prepared.invocation.execution_policy.model_copy(
                    update={
                        "max_model_steps": 2,
                        "max_model_requests": 2,
                        "output_instructions": "本次能力验证：先用memory_search"
                        "查找昨天借相机的记录。"
                        "收到结果后返回claims与message，核对借用旧事，不输出直接消息对象。",
                    }
                )
            }
        )
        result = await prepared.agent.run(invocation)
        assert result.status is AgentRunStatus.COMPLETED, result.model_dump(mode="json")
        assert result.usage_summary.tool_call_count >= 1
        assert result.usage_summary.model_request_count == 2
        assert isinstance(result.output.payload, CheckedCharacterExpression)
        (tmp_path / "real-expression.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        receipt = app.handler.commit.commit(lease, invocation, result)
        assert receipt.message_id
        with app.database.read() as connection:
            private = connection.execute(
                "SELECT claims_json FROM conversation_claims WHERE result_id=?",
                (receipt.result_id,),
            ).fetchone()
            assert private is not None and isinstance(json.loads(private[0]), list)
            public = json.loads(
                connection.execute(
                    "SELECT payload_json FROM conversation_results WHERE result_id=?",
                    (receipt.result_id,),
                ).fetchone()[0]
            )
            assert "claims" not in public["output"]["payload"]
            assert "thought" not in public["output"]["payload"]
            assert (
                public["output"]["payload"]["utterance"] == result.output.payload.message.utterance
            )
            row = connection.execute(
                "SELECT * FROM conversation_results WHERE result_id=?", (receipt.result_id,)
            ).fetchone()
            assert public["output"]["contract"]["version"] == "v1"
            assert "private_claims" not in inspected_result(connection, row)
            inspected = inspected_result(connection, row, include_claims=True)
            assert inspected["private_claims"] == json.loads(private[0])
            assert inspected["agent_output_contract"].endswith(".v2")
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()

        exported = ConversationExport(app.database).export(
            "community", "conversation", first_sequence=1, through_sequence=1
        )
        exported_text = json.dumps(exported, ensure_ascii=False, default=str)
        assert '"private_claims"' not in exported_text
        assert '"claims"' not in exported_text

    expression_loop.run(run())
