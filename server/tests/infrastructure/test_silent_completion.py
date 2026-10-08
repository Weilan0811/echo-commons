import asyncio

import pytest
from test_application_lifecycle import settings_for

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


@pytest.mark.model
def test_real_model_silence_finishes_without_empty_message(tmp_path):
    settings = settings_for(tmp_path, workers=True)

    async def run():
        async with application_lifecycle(settings) as application:
            application.communities.create("社群", "Asia/Shanghai", community_id="community")
            application.communities.update("community", expected_version=0, status="active")
            application.communities.register_player("玩家", player_id="player")
            application.communities.join("community", ActorRef("player", "player"))
            application.characters.create("community", "xiaojin", character_id="one")
            application.conversations.create(
                "community",
                "direct",
                (ActorRef("player", "player"), ActorRef("character", "one")),
                conversation_id="conversation",
            )
            application.intake.send(
                "community",
                "conversation",
                PlayerMessage(
                    "player",
                    "silence",
                    "我需要安静一下，这条消息不用回复。请保持沉默，不要生成任何对外发言。",
                ),
            )
            async with asyncio.timeout(60):
                while True:
                    with application.database.read() as connection:
                        task = connection.execute("SELECT * FROM conversation_tasks").fetchone()
                        if task is not None and task["status"] == "completed":
                            result = connection.execute(
                                "SELECT * FROM conversation_results"
                            ).fetchone()
                            assert result["status"] == "approved"
                            assert '"status": "no_proposal"' in result["payload_json"]
                            assert (
                                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                                == 1
                            )
                            assert (
                                connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0]
                                == 0
                            )
                            assert (
                                connection.execute(
                                    "SELECT outcome FROM participation_decisions"
                                ).fetchone()[0]
                                == "silent"
                            )
                            assert (
                                connection.execute("SELECT status FROM social_turns").fetchone()[0]
                                == "completed"
                            )
                            break
                    await asyncio.sleep(0.1)

    asyncio.run(run())
