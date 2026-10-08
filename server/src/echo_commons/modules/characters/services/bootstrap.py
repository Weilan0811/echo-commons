from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.domain.instance import CharacterInstance, MemoryMode
from echo_commons.modules.characters.domain.state import StateEntry, StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.blueprints import BlueprintReader
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.memory.contracts import MemoryBootstrapper
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class CharacterBootstrap:
    def __init__(
        self,
        database: Database,
        catalog: BlueprintCatalog | BlueprintReader,
        communities: CommunityRepository,
        instances: InstanceRepository,
        states: StateRepository,
        memories: MemoryBootstrapper,
    ) -> None:
        self.database, self.catalog, self.communities = database, catalog, communities
        self.instances, self.states, self.memories = instances, states, memories

    def list(self, community_id: str) -> tuple[CharacterInstance, ...]:
        with self.database.read() as connection:
            self.communities.get(connection, community_id)
            return self.instances.list(connection, community_id)

    def create(
        self,
        community_id: str,
        blueprint_id: str,
        *,
        character_id: str | None = None,
        player_id: str | None = None,
        memory_mode: MemoryMode = MemoryMode.SIMPLE,
    ) -> CharacterInstance:
        memory_mode = MemoryMode(memory_mode)
        character_id = str(uuid4()) if character_id is None else character_id
        if not character_id.strip():
            raise ValueError("Character ID must be nonempty")
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            self.communities.get(connection, community_id)
            if player_id is not None:
                self.communities.require_member(
                    connection, community_id, ActorRef("player", player_id)
                )
            blueprint = self.catalog.require_instantiable(connection, blueprint_id, player_id)
            existing = connection.execute(
                "SELECT community_id FROM character_instances WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            if existing:
                if existing["community_id"] != community_id:
                    raise ConflictError("Character ID belongs to another community")
                instance = self.instances.get(connection, community_id, character_id)
                if (instance.blueprint_id, instance.blueprint_version) != (
                    blueprint_id,
                    blueprint.content_version,
                ):
                    raise ConflictError("Character ID already binds a different blueprint")
                if instance.memory_mode is not memory_mode:
                    raise ConflictError("Character ID already binds a different memory mode")
                return instance
            materials = self.catalog.author_materials(
                connection, blueprint_id, blueprint.content_version
            )
            connection.execute(
                "INSERT INTO character_instances (character_id, community_id, "
                "blueprint_id, blueprint_version, created_at_utc, updated_at_utc, "
                "memory_mode, memory_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    character_id,
                    community_id,
                    blueprint_id,
                    blueprint.content_version,
                    utc_text(now),
                    utc_text(now),
                    memory_mode.value,
                    "preparing" if materials else "ready",
                ),
            )
            connection.execute(
                "INSERT INTO community_members VALUES (?, ?, ?, ?)",
                (community_id, "character", character_id, utc_text(now)),
            )
            for kind in StateKind:
                self.states.add(
                    connection,
                    StateEntry(
                        str(uuid4()),
                        community_id,
                        character_id,
                        kind,
                        getattr(blueprint.initial_state, kind.value),
                        "initialization",
                        f"{blueprint_id}@{blueprint.content_version}",
                        1,
                        now,
                    ),
                )
            self.memories.seed(
                connection, community_id, character_id, blueprint.memory_preload, now
            )
            if materials:
                self.memories.prepare(
                    connection,
                    character_id,
                    blueprint_id,
                    blueprint.content_version,
                    materials,
                    now,
                )
            return self.instances.get(connection, community_id, character_id)

    def retry_memory(
        self, community_id: str, character_id: str, *, player_id: str
    ) -> CharacterInstance:
        with self.database.transaction() as connection:
            self.communities.require_member(connection, community_id, ActorRef("player", player_id))
            instance = self.instances.get(connection, community_id, character_id)
            self.catalog.require_instantiable(connection, instance.blueprint_id, player_id)
            if instance.memory_status.value == "failed":
                self.memories.retry(connection, character_id, datetime.now(UTC))
            return self.instances.get(connection, community_id, character_id)
