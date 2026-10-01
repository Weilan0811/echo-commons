from __future__ import annotations

from pathlib import Path

import pytest

from echo_server.agents.character import CharacterAgent
from echo_server.agents.factory import build_default_character_agent
from echo_server.agents.harness import EchoNativeBackend
from echo_server.config import Settings
from echo_server.services.model_gateway import (
    ModelConfigurationError,
    ModelEntry,
    ModelRegistry,
    ModelRoute,
    load_model_registry,
    resolve_agent_route,
)


def make_entry(entry_id: str, credential_ref: str) -> ModelEntry:
    return ModelEntry(
        entry_id=entry_id,
        model_vendor="test",
        model=entry_id,
        base_url="https://example.test/v1",
        credential_ref=credential_ref,
        access_route="test-route",
        max_retries=0,
        retry_backoff_seconds=0,
    )


def make_registry(*, strong_enabled: bool = True) -> ModelRegistry:
    light = make_entry("light-entry", "light-key")
    strong = make_entry("strong-entry", "strong-key")
    return ModelRegistry(
        backend="openai_compatible",
        active_profile="light",
        profiles={"light": light.entry_id, "strong": strong.entry_id},
        entries={light.entry_id: light, strong.entry_id: strong},
        credentials={"light-key": "configured"},
        task_profiles={
            "conversation.reply": "light",
            "memory.maintenance": "strong",
        },
        strong_enabled=strong_enabled,
    )


def test_task_routing_uses_configured_profiles_and_explicit_strong_downgrade():
    routing = make_registry(strong_enabled=False)

    assert routing.route_for("conversation.reply") == ModelRoute(
        task_kind="conversation.reply",
        requested_profile="light",
        resolved_profile="light",
    )
    assert routing.route_for("memory.maintenance") == ModelRoute(
        task_kind="memory.maintenance",
        requested_profile="strong",
        resolved_profile="light",
        fallback_reason="strong_disabled",
    )


def test_task_routing_does_not_inspect_credentials_or_call_failures():
    registry = make_registry(strong_enabled=True)

    route = registry.route_for("memory.maintenance")

    assert route.requested_profile == "strong"
    assert route.resolved_profile == "strong"
    assert route.fallback_reason is None


def test_legacy_agent_without_route_keeps_its_model_profile():
    class LegacyAgent:
        model_profile = "stub"

    assert resolve_agent_route(LegacyAgent(), "conversation.reply") == ModelRoute(
        task_kind="conversation.reply",
        requested_profile="stub",
        resolved_profile="stub",
    )


def test_model_registry_rejects_a_route_to_an_unknown_profile():
    with pytest.raises(ModelConfigurationError, match="unknown profile"):
        ModelRegistry(
            backend="auto",
            active_profile="light",
            profiles={"light": "light-entry"},
            entries={"light-entry": make_entry("light-entry", "light-key")},
            credentials={},
            task_profiles={"memory.maintenance": "strong"},
        )


def test_committed_registry_declares_the_s4_routes():
    registry = load_model_registry(secrets_path=Path("missing-model-secrets.toml"))

    assert registry.active_profile == "light"
    assert registry.strong_enabled is True
    assert registry.route_for("conversation.reply").resolved_profile == "light"
    assert registry.route_for("memory.maintenance").resolved_profile == "strong"
    assert registry.route_for("character.reflection").resolved_profile == "strong"
    assert registry.route_for("narrative.important").resolved_profile == "strong"


def write_registry(tmp_path: Path) -> tuple[Path, Path]:
    registry_path = tmp_path / "model-registry.toml"
    secrets_path = tmp_path / "model-secrets.toml"
    registry_path.write_text(
        """
[runtime]
backend = "openai_compatible"
active_profile = "light"

[profiles]
light = "light-entry"
strong = "strong-entry"

[routing]
strong_enabled = false

[routing.task_profiles]
"conversation.reply" = "light"
"memory.maintenance" = "strong"

[entries.light-entry]
model_vendor = "test"
model = "light-model"
base_url = "https://example.test/v1"
credential_ref = "test"
access_route = "test-route"

[entries.strong-entry]
model_vendor = "test"
model = "strong-model"
base_url = "https://example.test/v1"
credential_ref = "test"
access_route = "test-route"
""",
        encoding="utf-8",
    )
    secrets_path.write_text('[credentials]\ntest = "test-key"\n', encoding="utf-8")
    return registry_path, secrets_path


def test_factory_builds_echo_native_backend_and_attaches_routing(tmp_path: Path):
    registry_path, secrets_path = write_registry(tmp_path)
    settings = Settings(
        model_registry_path=str(registry_path),
        model_secrets_path=str(secrets_path),
    )

    agent = build_default_character_agent(settings)

    assert isinstance(agent, CharacterAgent)
    assert isinstance(agent.backend, EchoNativeBackend)
    assert agent.agent_id == "xiaojin.character"
    assert agent.character_id == "xiaojin"
    assert agent.route_for("memory.maintenance").resolved_profile == "light"
    assert agent.route_for("memory.maintenance").fallback_reason == "strong_disabled"
