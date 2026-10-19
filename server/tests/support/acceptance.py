from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


def create_conversation(application, *, greeting="两位小槿，请各自说一句今天想一起做什么。"):
    application.communities.create("验收社群", "UTC", community_id="community")
    application.communities.update("community", expected_version=0, status="active")
    application.communities.register_player("玩家", player_id="player")
    application.communities.join("community", ActorRef("player", "player"))
    for character in ("first", "second"):
        application.characters.create(
            "community", "xiaojin", character_id=character, memory_mode="simple"
        )
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
        PlayerMessage("player", "greeting", greeting),
    )
    application.planner.plan()
