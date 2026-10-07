import asyncio
import json
import logging
import shutil
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError
from test_application_lifecycle import settings_for

from echo_commons.agents.harness.tools import ToolAuthorizationError
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition
from echo_commons.infrastructure.models.protocol import ToolCall
from echo_commons.infrastructure.observability.logging import JsonLogFormatter
from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.shared.actors import ActorRef


def create_conversation(application):
    application.communities.create("验收社群", "UTC", community_id="community")
    application.communities.update("community", expected_version=0, status="active")
    application.communities.register_player("玩家", player_id="player")
    application.communities.join("community", ActorRef("player", "player"))
    for character in ("first", "second"):
        application.characters.create("community", "xiaojin", character_id=character)
    application.conversations.create(
        "community",
        "group",
        (
            ActorRef("player", "player"),
            ActorRef("character", "first"),
            ActorRef("character", "second"),
        ),
        conversation_id="conversation",
    )
    application.intake.send(
        "community",
        "conversation",
        PlayerMessage("player", "greeting", "两位小槿，请各自说一句今天想一起做什么。"),
    )
    application.planner.plan()


def test_authored_capability_removal_changes_prompt_tools_and_execution_permissions(tmp_path):
    root = tmp_path / "identity"
    shutil.copytree(Path(files("echo_commons").joinpath("resources/identity")), root)
    capabilities = root / "blueprints/xiaojin/capabilities.yaml"
    content = yaml.safe_load(capabilities.read_text(encoding="utf-8"))
    content["capabilities"] = []
    capabilities.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    settings = settings_for(tmp_path, workers=False).model_copy(update={"identity_root": str(root)})

    async def run():
        async with application_lifecycle(settings) as application:
            create_conversation(application)
            lease = await application.queue.claim("capability-check", utc_now())
            execution = application.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
            assert execution.invocation.context.action_space.tools == ()
            assert execution.invocation.execution_policy.allowed_tools == ()
            registry = application.handler.execution.agents.bindings[
                execution.invocation.identity.purpose
            ].backend._loop.tools
            assert registry.has("memory_search")
            assert registry.definitions(execution.invocation.execution_policy.allowed_tools) == ()
            with pytest.raises(ToolAuthorizationError):
                await registry.execute(
                    ToolCall(call_id="denied", name="memory_search", arguments={"query": "晚餐"}),
                    execution.invocation,
                )
            assert application.gateway._clients == {}

    asyncio.run(run())


def test_normal_logging_excludes_private_text_and_credentials():
    record = logging.LogRecord("echo_commons", logging.INFO, __file__, 1, "model.call", (), None)
    record.prompt = "私有消息草莓417"
    record.credential = "private-credential"
    record.thought = "角色内部想法"
    record.invocation_id = "invocation"
    record.input_tokens = 12
    formatted = JsonLogFormatter().format(record)
    assert json.loads(formatted)["input_tokens"] == 12
    assert "invocation" in formatted
    assert all(
        value not in formatted
        for value in (
            record.prompt,
            record.credential,
            record.thought,
        )
    )


def test_same_blueprint_across_communities_keeps_all_instance_facts_independent(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as application:
            application.communities.register_player("玩家", player_id="player")
            sources = {}
            for community in ("one", "two"):
                application.communities.create(community, "UTC", community_id=community)
                application.communities.update(community, expected_version=0, status="active")
                application.communities.join(community, ActorRef("player", "player"))
                character = f"character-{community}"
                application.characters.create(
                    community, "xiaojin", character_id=character, memory_mode="full"
                )
                application.conversations.create(
                    community,
                    "direct",
                    (ActorRef("player", "player"), ActorRef("character", character)),
                    conversation_id=f"conversation-{community}",
                )
                sources[community] = application.intake.send(
                    community,
                    f"conversation-{community}",
                    PlayerMessage("player", f"input-{community}", f"只有{community}社群的经历"),
                )
            now = utc_now()
            with application.database.transaction() as connection:
                application.reflection_graph_commit.facts.characters.apply(
                    connection,
                    "one",
                    "character-one",
                    "message",
                    sources["one"].message_id,
                    (
                        RelationshipChange(
                            ActorRef("player", "player"),
                            RelationshipDimension.TRUST,
                            RelationshipDirection.UP,
                            2,
                            now,
                        ),
                    ),
                    (StateChange(StateKind.MOOD, "受到帮助后的安心"),),
                    now,
                )
            assert len(application.planner.plan()) == 2
            with application.database.read() as connection:
                tasks = connection.execute("SELECT * FROM conversation_tasks").fetchall()
                snapshots = {
                    row["community_id"]: application.handler.execution.tasks.snapshot(
                        connection, row["task_id"]
                    )
                    for row in tasks
                }
                assert len(tasks) == 2
                first, second = snapshots["one"], snapshots["two"]
                assert first.self.mood == "受到帮助后的安心"
                assert second.self.mood == ""
                assert len(first.self.relationships) == len(second.self.relationships) == 1
                assert first.self.relationships[0].relationship_type == "acquaintance"
                assert second.self.relationships[0].relationship_type == "stranger"
                relation = connection.execute(
                    "SELECT community_id,observer_character_id FROM relationship_state"
                ).fetchall()
                assert [tuple(row) for row in relation] == [("one", "character-one")]
                assert {item.memory_id for item in first.memory.resident}.isdisjoint(
                    item.memory_id for item in second.memory.resident
                )
                for community, snapshot in snapshots.items():
                    assert snapshot.scope.character_id == f"character-{community}"
                    assert (
                        snapshot.perspective.inputs[0].message_id == sources[community].message_id
                    )
                    other = "two" if community == "one" else "one"
                    assert sources[other].message_id not in snapshot.model_dump_json()
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    asyncio.run(run())


def test_reflection_advertised_schema_requires_action_and_evidence():
    adapter = TypeAdapter(ReflectionNodeAction)
    schema = adapter.json_schema()
    kinds = {
        "segment_summary",
        "relationship_reflection",
        "state_reflection",
        "continuity_digest",
        "long_term_memory_page",
        "graph_extraction",
        "diary",
        "view_refresh",
        "no_op",
    }
    actions = [
        definition
        for definition in schema["$defs"].values()
        if definition.get("properties", {}).get("kind", {}).get("const") in kinds
    ]
    assert len(actions) == 9
    assert all("kind" in action["required"] for action in actions)
    assert all(
        "evidence_refs" in action["required"]
        for action in actions
        if action["properties"]["kind"]["const"] != "no_op"
    )
    with pytest.raises(ValidationError, match="Unable to extract tag"):
        adapter.validate_python({"reason": "没有新的材料"})
    assert adapter.validate_python({"kind": "no_op", "reason": "没有新的材料"}).kind == "no_op"


@pytest.mark.model
def test_real_configuration_failure_preserves_other_success_and_next_input(tmp_path):
    credentials = tmp_path / "missing-secrets.toml"
    credentials.write_text("[credentials]\n", encoding="utf-8")
    settings = settings_for(tmp_path, workers=False)
    missing = settings.model_copy(update={"model_secrets_path": str(credentials)})

    async def run():
        async with application_lifecycle(missing) as application:
            create_conversation(application)
            failed = await application.queue.claim("missing-credentials", utc_now())
            outcome = await application.handler.execute(failed)
            assert outcome.disposition is Disposition.RECOVERY_REQUIRED
            assert outcome.recovery.failure.code == "provider_not_configured"
            assert await application.queue.apply_recovery(
                failed,
                utc_now(),
                outcome.recovery,
            )
            assert application.gateway._clients == {}
        async with application_lifecycle(settings) as application:
            remaining = await application.queue.claim("configured-worker", utc_now())
            assert remaining.task_id != failed.task_id
            outcome = await application.handler.execute(remaining)
            assert outcome.disposition is Disposition.COMPLETED
            with application.database.read() as connection:
                tasks = connection.execute("SELECT status FROM conversation_tasks").fetchall()
                assert sorted(row[0] for row in tasks) == ["completed", "failed"]
                assert (
                    connection.execute("SELECT status FROM social_turns").fetchone()[0]
                    == "completed"
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE sender_kind='character'"
                    ).fetchone()[0]
                    == 1
                )
            application.intake.send(
                "community", "conversation", PlayerMessage("player", "next", "我们开始准备晚餐吧。")
            )
            assert len(application.planner.plan()) == 1

    asyncio.run(run())
