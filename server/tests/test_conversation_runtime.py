from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from echo_server.agents.contracts import (
    CharacterMessageProposal,
    InvocationOrigin,
    ProposalEnvelope,
    ProposalKind,
)
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.proposals import ProposalDecision
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.domain.task import TaskStatus
from echo_server.main import create_app
from echo_server.runtime.application_runtime import (
    ApplicationRuntime,
    IdempotencyConflictError,
    decode_cursor,
    encode_cursor,
)
from echo_server.runtime.proposals import ProposalRegistry, ProposalReviewContext, ProposalReviewer
from echo_server.runtime.proposals.handlers import CharacterMessageHandler
from echo_server.store.database import Database


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_path=str(tmp_path / "echo.sqlite3"), worker_enabled=False, retry_backoff_seconds=0
    )


async def submit(
    runtime: ApplicationRuntime, text: str = "hello", client_msg_id=None, timestamp=None
):
    timestamp = timestamp or datetime.now(UTC)
    return await runtime.submit_message(
        SubmitMessageCommand(
            account_id=runtime.settings.account_id,
            conversation_id=runtime.settings.default_conversation_id,
            player_text=text,
            images=(),
            client_msg_id=client_msg_id or uuid4(),
            local_timestamp=timestamp,
        )
    )


async def seed_s25_runtime(runtime: ApplicationRuntime) -> None:
    now = runtime.clock()
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.world_states.save(
            WorldState(state_version=0, world_time_utc=now, updated_at_utc=now),
            connection=connection,
        )
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=now,
            ),
            connection=connection,
        )
        await runtime.participants.save(
            ConversationParticipant(
                conversation_id=runtime.settings.default_conversation_id,
                character_id=runtime.settings.default_character_id,
                joined_at_utc=now,
            ),
            account_id=runtime.settings.account_id,
            connection=connection,
        )


@pytest.mark.asyncio
async def test_t1_is_idempotent_and_conflicts_on_payload_change(settings):
    runtime = ApplicationRuntime(Database(settings.database_path), StubCharacterAgent(), settings)
    await runtime.start()
    client_msg_id = uuid4()
    timestamp = datetime.now(UTC)
    first = await submit(runtime, "exact", client_msg_id, timestamp)
    replay = await submit(runtime, "exact", client_msg_id, timestamp)
    assert replay == first
    with pytest.raises(IdempotencyConflictError):
        await submit(runtime, "different", client_msg_id, timestamp)
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM messages"))["count"] == 1
    await runtime.stop()


def test_cursor_is_versioned_and_opaque():
    cursor = encode_cursor(42)
    assert cursor != "42"
    assert decode_cursor(cursor) == 42


def test_reviewer_is_deterministic_and_dispatches_character_message_handler():
    reviewer = ProposalReviewer(
        registry=ProposalRegistry((CharacterMessageHandler(max_utterance_length=10),)),
    )
    invocation_id = uuid4()
    valid = ProposalEnvelope(
        proposal_id=uuid4(),
        kind=ProposalKind.CHARACTER_MESSAGE,
        origin=InvocationOrigin(invocation_id=invocation_id),
        payload=CharacterMessageProposal(
            character_id="xiaojin",
            thought="先听听。",
            utterance="ok",
        ),
    )
    context = ProposalReviewContext(
        expected_agent_id="agent",
        expected_agent_kind="character",
        expected_character_id="xiaojin",
        task_status=TaskStatus.PROCESSING,
        lease_owner="worker",
        worker_id="worker",
        lease_valid=True,
        expected_context_version="v1",
        actual_context_version="v1",
        expected_invocation_id=invocation_id,
    )
    result = reviewer.review(valid, context=context)
    assert result.decision is ProposalDecision.APPROVED
    invalid = valid.model_copy(
        update={
            "payload": valid.payload.model_copy(update={"utterance": " "}),
        }
    )
    result = reviewer.review(invalid, context=context)
    assert result.decision is ProposalDecision.REJECTED
    assert result.code.value == "empty_utterance"
    invalid_thought = valid.model_copy(
        update={
            "payload": valid.payload.model_copy(update={"thought": " "}),
        }
    )
    result = reviewer.review(invalid_thought, context=context)
    assert result.decision is ProposalDecision.APPROVED


@pytest.mark.asyncio
async def test_api_contract_and_unsupported_image_rejection(settings):
    app = __import__("echo_server.main", fromlist=["create_app"]).create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        payload = {
            "conversationId": "xiaojin",
            "playerText": "hello",
            "images": [],
            "clientMsgId": str(uuid4()),
            "localTimestamp": datetime.now(UTC).isoformat(),
        }
        response = await client.post("/message/send", json=payload)
        assert response.status_code == 202
        assert set(response.json()) == {"accepted", "messageId", "clientMsgId", "traceId"}
        bad = {**payload, "clientMsgId": str(uuid4()), "images": ["image://one"]}
        response = await client.post("/message/send", json=bad)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"
        blank = {**payload, "clientMsgId": str(uuid4()), "playerText": "   "}
        response = await client.post("/message/send", json=blank)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_lifespan_worker_completes_the_http_conversation(settings):
    live_settings = replace(settings, worker_enabled=True)
    app = create_app(live_settings, StubCharacterAgent({"xiaojin": "async reply"}))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await seed_s25_runtime(app.state.runtime)
        response = await client.post(
            "/message/send",
            json={
                "conversationId": "xiaojin",
                "playerText": "hello",
                "images": [],
                "clientMsgId": str(uuid4()),
                "localTimestamp": datetime.now(UTC).isoformat(),
            },
        )
        assert response.status_code == 202
        deadline = asyncio.get_running_loop().time() + live_settings.quiet_window_seconds + 10
        while asyncio.get_running_loop().time() < deadline:
            synced = await client.get("/message/sync")
            if len(synced.json()["messages"]) == 2:
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail(f"worker did not complete: {app.state.worker.failure!r}")
        assert [message["text"] for message in synced.json()["messages"]] == [
            "hello",
            "async reply",
        ]


@pytest.mark.asyncio
async def test_transaction_reads_never_observe_uncommitted_state(settings):
    runtime = ApplicationRuntime(Database(settings.database_path), StubCharacterAgent(), settings)
    await runtime.start()
    async with runtime.database.transaction(immediate=True) as connection:
        await connection.execute("INSERT INTO meta(key, value) VALUES ('uncommitted', 'yes')")
        outside = await runtime.database.fetchone(
            "SELECT value FROM meta WHERE key = 'uncommitted'"
        )
        assert outside is None
    committed = await runtime.database.fetchone("SELECT value FROM meta WHERE key = 'uncommitted'")
    assert committed["value"] == "yes"
    await runtime.stop()


def test_openapi_contract_is_current(settings):
    contract_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "openapi" / "echo-agent-service.json"
    )
    expected = json.loads(contract_path.read_text(encoding="utf-8"))
    assert create_app(settings).openapi() == expected
