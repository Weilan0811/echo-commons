import sqlite3
from dataclasses import dataclass
from datetime import datetime

from echo_commons.agents.contracts.context import RelationshipView, SelfContext
from echo_commons.agents.contracts.input import SourceVersion
from echo_commons.modules.characters.contracts import InstanceReader, StateReader
from echo_commons.modules.characters.domain.instance import MemoryMode
from echo_commons.modules.characters.domain.relationship import RelationshipKey
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.services.blueprints import BlueprintReader
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.perspective.contracts import ActorNames
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class CharacterContextBuild:
    self_context: SelfContext
    source_versions: tuple[SourceVersion, ...]


class CharacterContext:
    def __init__(
        self,
        catalog: BlueprintCatalog | BlueprintReader,
        instances: InstanceReader,
        states: StateReader,
        relationships: RelationshipRepository,
        names: ActorNames,
        capabilities: CapabilityResolver,
    ) -> None:
        self.catalog, self.instances, self.states = catalog, instances, states
        self.relationships, self.names, self.capabilities = relationships, names, capabilities

    def prepare(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        targets: frozenset[ActorRef],
        now: datetime,
        allowed_tools: frozenset[str],
    ) -> CharacterContextBuild:
        instance = self.instances.get(connection, community_id, character_id)
        blueprint = self.catalog.get(connection, instance.blueprint_id, instance.blueprint_version)
        if (
            blueprint.content_version != instance.blueprint_version
            or blueprint.voice is None
            or blueprint.relational_dynamics is None
        ):
            raise ValueError("The bound character blueprint is incomplete or unavailable")
        states = {
            kind: self.states.latest(connection, character_id, kind, now) for kind in StateKind
        }
        if instance.memory_mode is MemoryMode.SIMPLE:
            states = {kind: None for kind in StateKind}
        known = set(targets)
        known.update(
            ActorRef(key.target_kind.value, key.target_id)
            for key in self.relationships.keys(connection, community_id, character_id)
        )
        if instance.memory_mode is MemoryMode.SIMPLE:
            known.clear()
        relations, versions = (
            [],
            [
                SourceVersion(
                    kind="blueprint",
                    source_id=blueprint.resource_id,
                    version=blueprint.content_version,
                )
            ],
        )
        for target in sorted(known, key=lambda actor: (actor.kind.value, actor.actor_id)):
            if target == ActorRef("character", character_id):
                continue
            state = self.relationships.get(
                connection,
                RelationshipKey(community_id, character_id, target.kind.value, target.actor_id),
                now,
            )
            relations.append(
                RelationshipView(
                    target=target,
                    target_name=self.names.actor_name(connection, community_id, target),
                    relationship_type=state.relationship_type.value,
                    attitude=state.attitude_summary,
                )
            )
            versions.append(
                SourceVersion(
                    kind="relationship",
                    source_id=f"{character_id}/{target.kind.value}/{target.actor_id}",
                    version=str(state.state_version),
                )
            )
        versions.extend(
            SourceVersion(
                kind="character_state", source_id=entry.entry_id, version=str(entry.state_version)
            )
            for entry in states.values()
            if entry is not None
        )
        versions.extend(
            SourceVersion(
                kind="identity_resource",
                source_id=resource.resource_id,
                version=resource.content_version,
            )
            for resource in (
                self.catalog.agent_contract,
                blueprint.profile,
                blueprint.voice,
                blueprint.relational_dynamics,
                blueprint.capabilities_resource,
            )
            if resource is not None
        )
        tools = self.capabilities.tools(blueprint, allowed_tools)
        return CharacterContextBuild(
            SelfContext(
                character_id=character_id,
                name=blueprint.display_name,
                blueprint_id=blueprint.resource_id,
                blueprint_version=blueprint.content_version,
                agent_contract=self.catalog.agent_contract.content,
                profile=blueprint.profile.content,
                voice=blueprint.voice.content,
                relational_dynamics=blueprint.relational_dynamics.content,
                availability=instance.availability_status,
                mood=states[StateKind.MOOD].value if states[StateKind.MOOD] else "",
                physical_state=states[StateKind.PHYSICAL].value
                if states[StateKind.PHYSICAL]
                else "",
                activity=states[StateKind.ACTIVITY].value if states[StateKind.ACTIVITY] else "",
                relationships=tuple(relations),
                capabilities=tools,
            ),
            tuple(versions),
        )
