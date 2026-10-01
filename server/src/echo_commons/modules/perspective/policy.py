from __future__ import annotations

from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message


def can_observe(message: Message, membership: Membership, upper_sequence: int) -> bool:
    return (
        message.community_id == membership.community_id
        and message.conversation_id == membership.conversation_id
        and message.sequence <= upper_sequence
        and membership.covers(message.sequence)
        and membership.membership_id in message.audience
    )
