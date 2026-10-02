from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial
from echo_commons.shared.actors import ActorRef


def source_actors(snapshot: GraphContextSnapshot) -> frozenset[ActorRef]:
    actors = set()
    for material in snapshot.materials:
        if isinstance(material, MessageMaterial):
            actors.add(material.message.sender)
            actors.update(material.mentions)
    actors.discard(ActorRef("character", snapshot.scope.character_id))
    return frozenset(actors)
