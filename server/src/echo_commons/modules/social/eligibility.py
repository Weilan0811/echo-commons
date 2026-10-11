import sqlite3

from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.modules.social.domain import SocialTurn


class ParticipationEligibility:
    def __init__(self, instances: InstanceRepository, perspective: PerspectiveReader) -> None:
        self.instances, self.perspective = instances, perspective

    def reason(
        self,
        connection: sqlite3.Connection,
        turn: SocialTurn,
        member: Membership,
        original_membership: str,
        inputs: tuple[Message, ...],
    ) -> str | None:
        if member.left_at_utc is not None or member.membership_id != original_membership:
            return "member_left"
        if member.membership_id not in turn.audience:
            return "outside_audience"
        instance = self.instances.get(connection, turn.community_id, member.actor.actor_id)
        if instance.memory_status.value != "ready":
            return "character_memory_not_ready"
        if instance.availability_status is not AvailabilityStatus.AVAILABLE:
            return "unavailable"
        scope = ObservationScope(
            turn.community_id,
            turn.conversation_id,
            member.actor,
            turn.observation_max_sequence,
            member.membership_id,
        )
        if not all(self.perspective.visible(connection, scope, message) for message in inputs):
            return "source_not_visible"
        if inputs and all(message.sender == member.actor for message in inputs):
            return "self_trigger"
        return None
