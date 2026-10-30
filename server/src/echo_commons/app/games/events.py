from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.game_participation_repository import (
    GameParticipationRepository,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


class GameEvents:
    def __init__(self, communities: CommunityReader) -> None:
        self.communities = communities
        self.repository = GameParticipationRepository()
        self.activity_lifecycle = None

    def record_changed(
        self, connection, game_id: str, state_version: int, event_ids: tuple[str, ...]
    ):
        association = self.repository.find_association(connection, game_id)
        # 创建时宿主关联尚未建立，参与服务保存关联后登记同一项通知。
        if association is not None:
            if self.activity_lifecycle is not None:
                from echo_commons.execution.clock import utc_now

                self.activity_lifecycle.changed(
                    connection, utc_now(), game_id=game_id, include_processing=False
                )
            record_event(
                connection,
                EventReference(
                    EventKind.GAME,
                    association["community_id"],
                    game_id,
                    EventSource.GAME,
                    str(state_version),
                ),
            )

    def project(self, connection, event: EventReference, player_id: str):
        self.communities.require_member(
            connection, event.community_id, ActorRef("player", player_id)
        )
        association = self.repository.association(connection, event.object_id)
        if association["community_id"] != event.community_id:
            return None
        return {
            "community_id": event.community_id,
            "game_id": event.object_id,
            "state_version": int(event.source_id),
        }
