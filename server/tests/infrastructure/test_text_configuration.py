from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.infrastructure.models.openai_compatible import (
    OpenAICompatibleGateway,
    _request_params,
)
from echo_commons.infrastructure.models.protocol import ModelRequest
from echo_commons.infrastructure.models.registry import load_model_registry

SERVER = Path(__file__).resolve().parents[2]


def test_primary_only_configuration_covers_strong_tasks():
    registry = load_model_registry(SERVER / "config/model-registry.toml")
    entry = registry.resolve("light")
    single = replace(registry, profiles={"light": entry.entry_id}, entries={entry.entry_id: entry})
    assert single.resolve("strong") == entry
    assert single.route_for("character_interview_review").resolved_profile == "light"
    assert single.route_for("reflection").resolved_profile == "light"


def test_native_minimax_options_keep_required_thinking_and_omit_sampling():
    registry = load_model_registry(SERVER / "config/model-registry.toml")
    entry = registry.resolve(entry_id="minimax_flash")
    request = ModelRequest(
        invocation_id=uuid4(), trace_id=uuid4(), agent_id="configuration-check",
        model_profile="light", attempt=1, step_index=1,
        output_contract=OutputContractRef(kind="configuration", version="v1"), temperature=0.2,
    )
    params = _request_params(entry, request)
    assert params["extra_body"] == {"reasoning_split": True, "reasoning_effort": "low"}
    assert "temperature" not in params


@pytest.mark.model
@pytest.mark.asyncio
async def test_client_cache_separates_frozen_and_current_credential_references():
    registry = load_model_registry(
        SERVER / "config/model-registry.toml", SERVER / "config/model-secrets.toml"
    )
    entry = registry.resolve("light")
    alternate = next(
        reference
        for reference, key in registry.credentials.items()
        if reference != entry.credential_ref
        and key.strip()
        and key.strip() != registry.credential_for(entry)
    )
    changed = replace(entry, credential_ref=alternate)
    gateway = OpenAICompatibleGateway(registry)
    try:
        original = gateway._client_for(entry, registry.credential_for(entry))
        current = gateway._client_for(changed, registry.credential_for(changed))
        assert original is not current
        assert original.api_key == registry.credential_for(entry)
        assert current.api_key == registry.credential_for(changed)
        assert gateway._client_for(entry, registry.credential_for(entry)) is original
        assert gateway._client_for(changed, registry.credential_for(changed)) is current
        assert gateway.usage_tracker.snapshot() == {}
    finally:
        await gateway.close()
