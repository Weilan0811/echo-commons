from __future__ import annotations

import sqlite3

from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import ConflictError
from echo_commons.shared.message_sources import MessageSource, SystemSource
from echo_commons.shared.public import PublicDisplay


class CharacterIdentity:
    def __init__(self, instances: InstanceReader, catalog: BlueprintCatalog) -> None:
        self.instances, self.catalog = instances, catalog

    def name(self, connection: sqlite3.Connection, community_id: str, character_id: str) -> str:
        return self.display(
            connection, community_id, ActorRef("character", character_id)
        ).display_name

    def display(
        self, connection: sqlite3.Connection, community_id: str, actor: MessageSource
    ) -> PublicDisplay:
        if isinstance(actor, SystemSource):
            return PublicDisplay(actor=actor, display_name="系统")
        if actor.kind is ActorKind.PLAYER:
            player = CommunityRepository().player(connection, actor.actor_id)
            return PublicDisplay(actor=actor, display_name=player.display_name)
        character_id = actor.actor_id
        instance = self.instances.get(connection, community_id, character_id)
        blueprint = self.catalog.blueprint(instance.blueprint_id)
        if blueprint.content_version != instance.blueprint_version:
            raise ConflictError("Bound blueprint version is unavailable")
        return PublicDisplay(
            actor=actor, display_name=blueprint.display_name, avatar_url=blueprint.avatar_url
        )
