import asyncio
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from support.application import settings_for

from echo_commons.app.composition import assemble
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.models.budget import InputBudget
from echo_commons.infrastructure.models.decision import DecisionGateway
from echo_commons.infrastructure.models.decision_protocol import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionControls,
    DecisionRequest,
    NoulQuestion,
    ScoreQuestion,
)
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError, load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture

SERVER = Path(__file__).resolve().parents[2]


def test_local_tokenizer_counts_chinese_tokens_instead_of_utf8_bytes():
    budget = InputBudget(
        model_entry_id="startlux_local",
        context_window_tokens=8192,
        output_tokens=64,
        token_counter="hf:startlux-models/StartLux-Decision-v1.1-0.8B-Instant",
    )
    text = "大家有什么想法？我想听听你们的意见。"
    assert budget.count(text) == 9
    assert budget.count(text * 1000) > 8192


def registry():
    original = load_model_registry(SERVER / "config/model-registry.toml")
    return replace(original, decision=original.decision.model_copy(update={"enabled": True}))


def gateway_for(models, tmp_path):
    text = OpenAICompatibleGateway(models)
    budget = ModelBudget(text, 1)
    capture = AgentDebugCapture(tmp_path / "captures")
    return DecisionGateway(models, budget, debug_capture=capture), capture


def request(**changes):
    return DecisionRequest(
        invocation_id=uuid4(),
        trace_id=uuid4(),
        agent_id="decision-verification",
        state="订单重复扣款，用户今天需要完成付款。",
        questions={
            "team": ChoiceQuestion(
                instructions="请选择负责处理的团队。",
                criteria={"billing": "付款与退款", "shipping": "物流与配送"},
            )
        },
        **changes,
    )


def test_decision_config_defaults_off_and_uses_real_no_auth_entry(tmp_path):
    models = registry()
    assert models.resolve("decision").credential_ref is None
    assert models.decision.controls.think_mode == "never"
    source = (SERVER / "config/model-registry.toml").read_text(encoding="utf-8")
    path = tmp_path / "registry.toml"
    path.write_text(source, encoding="utf-8")
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_registry_path": str(path)}
    )
    app = assemble(settings)
    assert app.decisions is None
    unused = DecisionGateway(app.models, ModelBudget(app.gateway, 1))
    assert unused._client is None


def test_prepare_freezes_route_controls_and_deadline(tmp_path):
    gateway, _ = gateway_for(registry(), tmp_path)
    prepared = gateway.prepare(request())
    assert prepared.model_entry_id == "startlux_local"
    assert prepared.controls.think_mode == "never"
    restored = DecisionRequest.model_validate_json(prepared.model_dump_json())
    assert gateway.prepare(restored) == prepared
    only_primary = load_model_registry(SERVER / "config/model-registry.toml")
    primary = only_primary.resolve("light")
    only_primary = replace(
        only_primary, profiles={"light": primary.entry_id}, entries={primary.entry_id: primary}
    )
    restored_gateway = DecisionGateway(
        only_primary, ModelBudget(OpenAICompatibleGateway(only_primary), 1)
    )
    assert restored_gateway.prepare(restored).route == prepared.route
    changed = replace(gateway.registry.resolve("decision"), base_url="http://127.0.0.1:8091")
    updated, _ = gateway_for(
        replace(gateway.registry, entries={**gateway.registry.entries, changed.entry_id: changed}),
        tmp_path,
    )
    assert updated.prepare(restored) == prepared
    assert "invocation_id" not in prepared.payload()
    assert set(prepared.payload()["questions"]) == {"team"}


def test_input_rejects_unsupported_question_shapes():
    with pytest.raises(ValidationError):
        ScoreQuestion(instructions="严重程度", criteria=("只有一级",))
    with pytest.raises(ValidationError):
        ChoiceQuestion(instructions="", criteria={"a": "候选"})
    with pytest.raises(ValidationError):
        DecisionControls(gate=1.1)
    with pytest.raises(ValidationError):
        DecisionControls(allow_none="true")


def test_config_rejects_decision_profile_with_text_protocol():
    models = registry()
    with pytest.raises(ModelConfigurationError, match="protocol"):
        replace(models, decision=models.decision.model_copy(update={"profile": "light"}))


def test_real_connection_failure_has_bounded_retries_and_capture(tmp_path):
    models = registry()
    with socket.socket() as port:
        port.bind(("127.0.0.1", 0))
        entry = replace(
            models.resolve("decision"), base_url=f"http://127.0.0.1:{port.getsockname()[1]}"
        )
        models = replace(models, entries={**models.entries, entry.entry_id: entry})
        gateway, capture = gateway_for(models, tmp_path)

        async def run():
            try:
                with pytest.raises(ModelGatewayError) as failure:
                    await gateway.decide(request())
                assert failure.value.code == "temporary_unavailable"
                assert failure.value.provider_attempt == 2
            finally:
                await gateway.close()

        asyncio.run(run())
    calls = list(capture.directory.glob("*-model_call.json"))
    assert len(calls) == 2
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["error"]["code"] == "temporary_unavailable"
        for path in calls
    )


def test_queue_wait_honors_deadline_and_cancellation_without_request(tmp_path):
    gateway, _ = gateway_for(registry(), tmp_path)

    async def run():
        async with gateway.budget.slot():
            with pytest.raises(ModelGatewayError) as failure:
                await gateway.decide(
                    request(deadline_utc=datetime.now(UTC) + timedelta(seconds=0.02))
                )
            assert failure.value.code == "timeout" and failure.value.provider_attempt == 0
            task = asyncio.create_task(gateway.decide(request()))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert gateway._client is None
        assert gateway.budget._active == 0 and not gateway.budget._waiting

    asyncio.run(run())


def test_input_limit_and_expired_deadline_do_not_create_http_client(tmp_path):
    models = registry()
    models = replace(models, decision=models.decision.model_copy(update={"input_max_chars": 10}))
    gateway, _ = gateway_for(models, tmp_path)

    async def run():
        with pytest.raises(ModelGatewayError) as failure:
            await gateway.decide(request())
        assert failure.value.code == "input_too_large" and failure.value.provider_attempt == 0
        assert gateway._client is None
        other, _ = gateway_for(registry(), tmp_path)
        with pytest.raises(ModelGatewayError) as failure:
            await other.decide(request(deadline_utc=datetime.now(UTC) - timedelta(seconds=1)))
        assert failure.value.code == "timeout" and other._client is None

    asyncio.run(run())


@pytest.mark.model
def test_real_service_returns_all_question_types_and_original_probabilities(tmp_path):
    gateway, capture = gateway_for(registry(), tmp_path)
    source = request()
    source = source.model_copy(
        update={
            "questions": {
                **source.questions,
                "urgent": NoulQuestion(instructions="用户是否需要今天获得帮助？"),
                "severity": ScoreQuestion(
                    instructions="问题的严重程度。", criteria=("轻微", "中等", "严重")
                ),
            }
        }
    )

    async def run():
        try:
            result = await gateway.decide(source)
            assert result.answers["team"].choice == "billing"
            assert 0 <= result.answers["urgent"].noul <= 1
            assert result.answers["severity"].legend == {"0": "轻微", "1": "中等", "2": "严重"}
            assert result.model == gateway.registry.resolve("decision").model
            assert result.usage.input_tokens > 0 and result.usage.output_tokens == 0
            different = source.model_copy(
                update={"questions": {"another_question": source.questions["team"]}}
            )
            with pytest.raises(ValueError, match="questions"):
                result.validate_answers(gateway.prepare(different))
            assert gateway.usage_tracker.snapshot()["startlux"].model_request_count == 1
            document = json.loads(
                next(capture.directory.glob("*-model_call.json")).read_text(encoding="utf-8")
            )
            assert document["input"]["providerRequest"]["think_mode"] == "never"
            assert (
                document["output"]["rawProviderResponse"]["answers"]["team"]["probabilities"]
                == result.answers["team"].probabilities
            )
            assert next(capture.directory.glob("*-model_call.started.txt")).read_text(
                encoding="utf-8"
            )
        finally:
            await gateway.close()
        assert gateway._client.is_closed

    asyncio.run(run())


@pytest.mark.model
@pytest.mark.parametrize("selected", ("silent", "needs_understanding"))
def test_real_service_can_select_business_options_without_gateway_rules(tmp_path, selected):
    gateway, _ = gateway_for(registry(), tmp_path)
    source = request().model_copy(
        update={
            "state": f"当前步骤的指定结果是 {selected}。请严格选择这个同名选项。",
            "questions": {
                "participation": ChoiceQuestion(
                    instructions="选择当前步骤指定的结果。",
                    criteria={
                        "speak": "发言",
                        "silent": "沉默",
                        "needs_understanding": "进一步理解",
                    },
                )
            },
        }
    )

    async def run():
        try:
            response = await gateway.decide(source)
            assert isinstance(response.answers["participation"], ChoiceAnswer)
            assert response.answers["participation"].choice == selected
        finally:
            await gateway.close()

    asyncio.run(run())


@pytest.mark.model
def test_real_auto_think_controls_and_optional_none(tmp_path):
    gateway, _ = gateway_for(registry(), tmp_path)
    source = request(
        controls=DecisionControls(
            think_mode="auto",
            allow_none=True,
            return_details=True,
        )
    )

    async def run():
        try:
            result = await gateway.decide(source)
            answer = result.answers["team"]
            assert answer.choice == "billing"
            assert answer.none_probability is not None and answer.details is not None
        finally:
            await gateway.close()

    asyncio.run(run())


@pytest.mark.model
def test_real_http_error_does_not_retry_invalid_endpoint(tmp_path):
    models = registry()
    entry = replace(models.resolve("decision"), base_url="http://127.0.0.1:8090/missing")
    models = replace(models, entries={**models.entries, entry.entry_id: entry})
    gateway, _ = gateway_for(models, tmp_path)

    async def run():
        try:
            with pytest.raises(ModelGatewayError) as failure:
                await gateway.decide(request())
            assert failure.value.code == "invalid_request"
            assert failure.value.status_code == 404 and failure.value.provider_attempt == 1
        finally:
            await gateway.close()

    asyncio.run(run())


@pytest.mark.model
def test_application_constructs_and_closes_enabled_decision_client(tmp_path):
    source = (SERVER / "config/model-registry.toml").read_text(encoding="utf-8")
    path = tmp_path / "registry.toml"
    path.write_text(source.replace("enabled = false", "enabled = true", 1), encoding="utf-8")
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_registry_path": str(path)}
    )

    async def run():
        async with application_lifecycle(settings) as app:
            assert app.decisions is not None
            await app.decisions.decide(request())
            client = app.decisions._client
        assert client.is_closed

    asyncio.run(run())
