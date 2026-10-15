import asyncio
from pathlib import Path

import pytest
from support.application import settings_for

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


def test_startup_creates_schema_without_default_world_and_closes_workers(tmp_path):
    settings = settings_for(tmp_path, workers=False)

    async def run():
        async with application_lifecycle(settings) as application:
            assert application.started
            with application.database.read() as connection:
                assert connection.execute("SELECT COUNT(*) FROM communities").fetchone()[0] == 0
                assert (
                    connection.execute("SELECT COUNT(*) FROM character_instances").fetchone()[0]
                    == 0
                )
            assert application.gateway._clients == {}
        assert not application.started
        assert application.supervisor._tasks == []

    asyncio.run(run())
    assert Path(settings.database_path).exists()


@pytest.mark.model
def test_background_workers_run_two_real_characters_and_deliver_traces(tmp_path):
    settings = settings_for(tmp_path, workers=True).model_copy(update={"max_chain_messages": 2})

    async def run():
        async with application_lifecycle(settings) as application:
            await asyncio.to_thread(
                application.communities.create, "社群", "Asia/Shanghai", community_id="community"
            )
            await asyncio.to_thread(
                application.communities.update, "community", expected_version=0, status="active"
            )
            await asyncio.to_thread(
                application.communities.register_player, "玩家", player_id="player"
            )
            await asyncio.to_thread(
                application.communities.join, "community", ActorRef("player", "player")
            )
            for character in ("one", "two"):
                await asyncio.to_thread(
                    application.characters.create, "community", "xiaojin", character_id=character
                )
            await asyncio.to_thread(
                application.conversations.create,
                "community",
                "group",
                (
                    ActorRef("player", "player"),
                    ActorRef("character", "one"),
                    ActorRef("character", "two"),
                ),
                conversation_id="conversation",
            )
            await asyncio.to_thread(
                application.intake.send,
                "community",
                "conversation",
                PlayerMessage("player", "hello", "大家好，请各位说一句今天想一起做什么。"),
            )
            async with asyncio.timeout(90):
                while True:
                    with application.database.read() as connection:
                        completed = connection.execute(
                            "SELECT COUNT(*) FROM conversation_tasks WHERE status = 'completed'"
                        ).fetchone()[0]
                        traced = connection.execute(
                            "SELECT COUNT(*) FROM traces WHERE kind = 'task.completed'"
                        ).fetchone()[0]
                        if completed == 2 and traced == 2:
                            assert (
                                connection.execute(
                                    "SELECT COUNT(*) FROM messages WHERE sender_kind = 'character'"
                                ).fetchone()[0]
                                == 2
                            )
                            assert (
                                connection.execute("SELECT status FROM social_turns").fetchone()[0]
                                == "completed"
                            )
                            break
                    await asyncio.sleep(0.1)
            assert all(
                state.last_error_type is None for state in application.supervisor.states.values()
            )
            clients = tuple(application.gateway._clients.values())
        assert clients and all(client.is_closed() for client in clients)
        assert application.supervisor._tasks == []

    asyncio.run(run())
