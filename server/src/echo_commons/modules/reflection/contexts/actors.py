import json

from echo_commons.modules.reflection.contracts.context import (
    FactMaterial,
    GameEventMaterial,
    GraphContextSnapshot,
    MessageMaterial,
)
from echo_commons.shared.actors import ActorRef


def source_actors(snapshot: GraphContextSnapshot) -> frozenset[ActorRef]:
    actors = set()
    for material in snapshot.materials:
        if material.context_only:
            continue
        if isinstance(material, MessageMaterial):
            if isinstance(material.message.sender, ActorRef):
                actors.add(material.message.sender)
            actors.update(material.mentions)
        elif isinstance(material, GameEventMaterial):
            actors.update(material.actors)
        elif isinstance(material, FactMaterial) and material.fact_kind == "relationship":
            content = json.loads(material.content)
            actors.add(ActorRef(content["target_kind"], content["target_id"]))
        elif isinstance(material, GameEventMaterial):
            actors.update(material.actors)
        elif isinstance(material, FactMaterial) and material.fact_kind == "memory_fact":
            content = json.loads(material.content)
            actors.update(
                ActorRef(item["kind"], item["actor_id"])
                for item in json.loads(content.get("participants_json", "[]"))
            )
        elif isinstance(material, GameEventMaterial):
            actors.update(material.actors)
        elif isinstance(material, FactMaterial) and material.fact_kind == "memory_cognition":
            content = json.loads(material.content)
            if content.get("target_json"):
                target = json.loads(content["target_json"])
                actors.add(ActorRef(target["kind"], target["actor_id"]))
    actors.discard(ActorRef("character", snapshot.scope.character_id))
    return frozenset(actors)
