from echo_commons.shared.actors import ActorRef


def participant_ref(actor: ActorRef) -> str:
    return f"{actor.kind.value}:{actor.actor_id}"


def participant_actor(reference: str) -> ActorRef:
    kind, identity = reference.split(":", 1)
    return ActorRef(kind, identity)
