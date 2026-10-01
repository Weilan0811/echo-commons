from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import DEFAULT_LOG_PATH, Settings, load_settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.observability.logging import configure_logging, log_event
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.store.database import Database


def test_load_settings_uses_ignored_data_log_path_by_default():
    settings = load_settings()

    assert settings.log_path == DEFAULT_LOG_PATH
    assert settings.log_path is not None
    assert Path(settings.log_path).parts[-4:] == ("server", "data", "logs", "echo.log")


def test_empty_log_path_disables_file_output(tmp_path):
    source = Path(__file__).parents[1] / "config" / "settings.toml"
    config = tmp_path / "settings.toml"
    content = source.read_text(encoding="utf-8").replace(
        'log_path = "../data/logs/echo.log"', 'log_path = ""'
    )
    config.write_text(content, encoding="utf-8")

    assert load_settings(config).log_path is None


def test_logging_is_json_redacted_and_handler_setup_is_idempotent(tmp_path):
    log_path = tmp_path / "logs" / "echo.log"
    settings = Settings(log_path=str(log_path), log_level="INFO")

    logger = configure_logging(settings)
    try:
        configure_logging(settings)
        correlation_id = uuid4()
        log_event(
            logger,
            logging.INFO,
            "agent.call.completed",
            correlation_id=correlation_id,
            duration_ms=12,
            player_text="玩家原文不应进入日志",
            prompt="prompt 不应进入日志",
            model_output="完整模型输出不应进入日志",
        )
        for handler in logger.handlers:
            handler.flush()

        entry = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert entry["event"] == "agent.call.completed"
        assert entry["correlation_id"] == str(correlation_id)
        assert entry["duration_ms"] == 12
        raw_log = log_path.read_text(encoding="utf-8")
        assert "玩家原文不应进入日志" not in raw_log
        assert "prompt 不应进入日志" not in raw_log
        assert "完整模型输出不应进入日志" not in raw_log

        owned_handlers = [
            handler for handler in logger.handlers if getattr(handler, "_echo_owned", False)
        ]
        assert len(owned_handlers) == 2
    finally:
        configure_logging(Settings(log_path=None))


@pytest.mark.asyncio
async def test_runtime_emits_correlated_operational_events(tmp_path):
    log_path = tmp_path / "logs" / "echo.log"
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        log_path=str(log_path),
        worker_enabled=False,
        retry_backoff_seconds=0,
    )
    logger = configure_logging(settings)
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    clock = [now]
    runtime = ApplicationRuntime(
        Database(settings.database_path), StubCharacterAgent(), settings, clock=lambda: clock[0]
    )
    try:
        await runtime.start()
        async with runtime.database.transaction(immediate=True) as connection:
            await runtime.world_states.save(
                WorldState(state_version=0, world_time_utc=now, updated_at_utc=now),
                connection=connection,
            )
            await runtime.character_states.save(
                CharacterState(
                    character_id=settings.default_character_id,
                    availability_status=CharacterAvailabilityStatus.AVAILABLE,
                    state_version=0,
                    updated_at_utc=now,
                ),
                connection=connection,
            )
            await runtime.participants.save(
                ConversationParticipant(
                    conversation_id=settings.default_conversation_id,
                    character_id=settings.default_character_id,
                    joined_at_utc=now,
                ),
                account_id=settings.account_id,
                connection=connection,
            )
        command = SubmitMessageCommand(
            account_id=settings.account_id,
            conversation_id=settings.default_conversation_id,
            player_text="runtime integration secret",
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=now,
        )
        receipt = await runtime.submit_message(command)
        clock[0] = now + timedelta(seconds=6)
        worker = ConversationWorker(runtime, settings)
        assert await worker.run_once() is True
        await runtime.stop()

        for handler in logger.handlers:
            handler.flush()
        entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        event_names = {entry["event"] for entry in entries}
        assert {
            "runtime.started",
            "message.accepted",
            "task.created",
            "task.claimed",
            "agent.call.started",
            "agent.call.completed",
            "task.result_committed",
            "runtime.stopped",
        } <= event_names
        assert any(
            entry.get("correlation_id") == str(receipt.trace_id)
            for entry in entries
            if entry["event"] == "message.accepted"
        )
        raw_log = log_path.read_text(encoding="utf-8")
        assert "runtime integration secret" not in raw_log
    finally:
        configure_logging(Settings(log_path=None))
