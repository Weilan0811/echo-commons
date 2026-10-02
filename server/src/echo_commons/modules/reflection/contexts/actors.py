from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial
from echo_commons.shared.actors import ActorRef


def source_actors(snapshot: GraphContextSnapshot) -> frozenset[ActorRef]:
    actors = set()
    for material in snapshot.materials:
        if isinstance(material, MessageMaterial):
            if isinstance(material.message.sender, ActorRef):
                actors.add(material.message.sender)
            actors.update(material.mentions)
    actors.discard(ActorRef("character", snapshot.scope.character_id))
    return frozenset(actors)
