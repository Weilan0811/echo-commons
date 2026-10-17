import sqlite3

from echo_games.public import GameService, GameSummary

from echo_commons.modules.activities.contracts import CharacterParticipationReason
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import AvailabilityStatus, MemoryStatus
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import CharacterNotReady, ConflictError


class CharacterGameEligibility:
    def __init__(
        self,
        communities: CommunityReader,
        instances: InstanceReader,
        games: GameService,
    ) -> None:
        self.communities, self.instances, self.games = communities, instances, games

    def reason(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
        game: GameSummary,
    ) -> CharacterParticipationReason | None:
        if actor.kind is not ActorKind.CHARACTER:
            raise ValueError("Character participation requires a character")
        self.communities.require_member(connection, community_id, actor)
        instance = self.instances.get(connection, community_id, actor.actor_id)
        # 注册的游戏定义提供正式视图与事件；通用观察读取不需要模型执行能力。
        self.games.registry.resolve(game.game_type, game.ruleset_id, game.ruleset_version)
        if instance.memory_status is MemoryStatus.PREPARING:
            return "memory_preparing"
        if instance.memory_status is MemoryStatus.FAILED:
            return "memory_failed"
        if instance.availability_status is not AvailabilityStatus.AVAILABLE:
            return "unavailable"
        return None

    def require(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
        game: GameSummary,
    ) -> None:
        reason = self.reason(connection, community_id, actor, game)
        if reason in ("memory_preparing", "memory_failed"):
            raise CharacterNotReady("角色记忆尚未准备完成，请查看准备状态或重试。")
        if reason == "unavailable":
            raise ConflictError("角色目前无法参与活动，请查看角色状态。")
