import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError

from echo_commons.agents.contracts.context import (
    ContextSnapshot,
    EnvironmentContext,
    MemoryContext,
    PerspectiveContext,
    SelfContext,
    SnapshotScope,
)
from echo_commons.agents.contracts.input import ActionSpace
from echo_commons.agents.contracts.invocation import (
    AgentInvocation,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    InvocationScope,
)
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.contracts.refs import ContextInputRef
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ModelGatewayError, ModelRequest
from echo_commons.infrastructure.models.registry import ModelConfigurationError, load_model_registry
from echo_commons.modules.characters.templates.loader import (
    IdentityConfigurationError,
    load_blueprint_catalog,
)
from echo_commons.shared.actors import ActorKind, ActorRef

SERVER = Path(__file__).resolve().parents[2]


def test_packaged_blueprint_is_complete_and_initial():
    catalog = load_blueprint_catalog()
    blueprint = catalog.blueprint("xiaojin")
    assert catalog.schema_version == 1
    assert catalog.bundle_version == "0.1.0"
    assert catalog.agent_contract.content_version == "0.1.0"
    assert blueprint.content_version == "0.1.0"
    assert blueprint.voice.content.strip()
    assert blueprint.profile.content.strip()
    assert blueprint.relational_dynamics.content.strip()
    assert blueprint.capabilities[0].name == "memory_search"
    parameters = blueprint.capabilities[0].parameters
    parameters["properties"]["query"]["type"] = "integer"
    assert blueprint.capabilities[0].parameters["properties"]["query"]["type"] == "string"
    assert len(blueprint.memory_preload.memories) == 4
    assert all(
        memory.subject_kind == "self" and memory.subject_id == "self"
        for memory in blueprint.memory_preload.memories
    )
    with pytest.raises(TypeError):
        catalog.blueprints["other"] = blueprint


def test_explicit_missing_blueprint_root_is_rejected(tmp_path):
    with pytest.raises(IdentityConfigurationError, match="missing"):
        load_blueprint_catalog(tmp_path / "missing")


@pytest.mark.parametrize("change", ["old_schema", "missing_voice", "single_markdown"])
def test_invalid_blueprint_bundle_is_rejected(tmp_path, change):
    source = SERVER / "src/echo_commons/resources/identity"
    target = tmp_path / "identity"
    shutil.copytree(source, target)
    manifest = target / "manifest.yaml"
    values = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if change == "old_schema":
        values["schema_version"] = 2
    elif change == "missing_voice":
        (target / "blueprints/xiaojin/voice.md").unlink()
    else:
        values["blueprints"]["xiaojin"]["path"] = "blueprints/xiaojin/profile.md"
    manifest.write_text(yaml.safe_dump(values, allow_unicode=True), encoding="utf-8")
    with pytest.raises(IdentityConfigurationError):
        load_blueprint_catalog(target)


def test_settings_have_no_default_business_identities():
    settings = load_settings(SERVER / "config/settings.toml")
    assert Path(settings.database_path) == SERVER / "data/echo-commons.sqlite3"
    assert settings.identity_root is None
    assert settings.model_concurrency == 3
    assert settings.max_responders == 2
    assert (
        not {"account_id", "default_character_id", "default_conversation_id"}
        & type(settings).model_fields.keys()
    )
    assert create_app(settings).openapi()["info"]["version"] == "0.1.0"


def request():
    return ModelRequest(
        invocation_id=uuid4(),
        trace_id=uuid4(),
        agent_id="instance-a",
        model_profile="light",
        attempt=1,
        step_index=1,
        output_contract=CHARACTER_MESSAGE_CONTRACT,
    )


def test_model_request_has_one_output_contract():
    values = request().model_dump()
    assert "output_schema" not in values
    with pytest.raises(ValidationError):
        ModelRequest(**values, output_schema="character_message.v1")
    del values["output_contract"]
    with pytest.raises(ValidationError):
        ModelRequest(**values)


@pytest.mark.parametrize("backend", ["auto", "stub"])
def test_registry_rejects_simulated_backends(tmp_path, backend):
    config = (SERVER / "config/model-registry.toml").read_text(encoding="utf-8")
    path = tmp_path / "models.toml"
    path.write_text(
        config.replace('backend = "openai_compatible"', f'backend = "{backend}"'), encoding="utf-8"
    )
    with pytest.raises(ModelConfigurationError):
        load_model_registry(path, tmp_path / "absent-secrets.toml")


@pytest.mark.asyncio
async def test_missing_credentials_report_real_configuration_error(tmp_path):
    registry = load_model_registry(
        SERVER / "config/model-registry.toml", tmp_path / "absent-secrets.toml"
    )
    gateway = OpenAICompatibleGateway(registry)
    with pytest.raises(ModelGatewayError) as caught:
        await gateway.generate(request())
    assert caught.value.code == "provider_not_configured"
    assert caught.value.retryable is False
    assert caught.value.provider_attempt == 0


def snapshot():
    catalog = load_blueprint_catalog()
    blueprint = catalog.blueprint("xiaojin")
    return ContextSnapshot(
        snapshot_id="snapshot-a",
        prepared_at_utc=datetime.now(UTC),
        scope=SnapshotScope(
            community_id="community-a",
            character_id="instance-a",
            conversation_id="conversation-a",
            membership_id="membership-a",
            observation_upper_sequence=0,
        ),
        self=SelfContext(
            character_id="instance-a",
            name="小槿",
            blueprint_id="xiaojin",
            blueprint_version=blueprint.content_version,
            agent_contract=catalog.agent_contract.content,
            profile=blueprint.profile.content,
            voice=blueprint.voice.content,
            relational_dynamics=blueprint.relational_dynamics.content,
        ),
        perspective=PerspectiveContext(),
        memory=MemoryContext(),
        environment=EnvironmentContext(
            world_time_utc=datetime.now(UTC), community_status="active", conversation_kind="group"
        ),
        action_space=ActionSpace(output_contracts=(CHARACTER_MESSAGE_CONTRACT,)),
        source_versions=(),
    )


def test_snapshot_round_trip_and_invocation_scope():
    context = snapshot()
    assert ContextSnapshot.model_validate_json(context.model_dump_json()) == context
    with pytest.raises(ValidationError):
        context.scope.character_id = "instance-b"
    values = dict(
        identity=InvocationIdentity(
            agent_id="instance-a.character", purpose=InvocationPurpose.CONVERSATION_REPLY, attempt=1
        ),
        scope=InvocationScope(
            community_id="community-a",
            character_id="instance-a",
            task_id="task-a",
            source_kind="social_turn",
            source_id="turn-a",
        ),
        context=context,
        context_input=ContextInputRef(snapshot_id="snapshot-a"),
        output_contract=CHARACTER_MESSAGE_CONTRACT,
        execution_policy=ExecutionPolicy(model_profile="light"),
        correlation=Correlation(task_id="task-a", trace_id=uuid4()),
    )
    invocation = AgentInvocation(**values)
    assert invocation.context is context
    serialized = invocation.model_dump(mode="json")["context"]
    assert serialized == context.model_dump(mode="json")
    assert invocation.context.read_policy.conversation_id == context.scope.conversation_id
    assert invocation.context.read_policy.upper_sequence == context.scope.observation_upper_sequence
    values["scope"] = InvocationScope(
        community_id="community-b",
        character_id="instance-a",
        task_id="task-a",
        source_kind="social_turn",
        source_id="turn-a",
    )
    with pytest.raises(ValidationError, match="scope"):
        AgentInvocation(**values)


def test_actor_identity_and_registered_output_are_explicit():
    assert ActorRef(ActorKind.PLAYER, "player-a") != ActorRef(ActorKind.CHARACTER, "player-a")
    with pytest.raises(ValueError):
        ActorRef(ActorKind.PLAYER, "")
    registry = OutputRegistry()
    registry.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    assert registry.parse(CHARACTER_MESSAGE_CONTRACT, {"utterance": "你好"}).utterance == "你好"
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
