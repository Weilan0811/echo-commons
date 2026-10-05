from __future__ import annotations

from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message


def visible_message_sql(message_alias: str = "m", *, player_expression: str = "?") -> str:
    # SQL 查询使用与 can_observe 相同的区间和实际受众条件。
    return (
        "EXISTS (SELECT 1 FROM message_recipients vr "
        "JOIN conversation_memberships vm ON vm.membership_id=vr.membership_id "
        f"WHERE vr.message_id={message_alias}.message_id AND vm.actor_kind='player' "
        f"AND vm.actor_id={player_expression} AND vm.community_id={message_alias}.community_id "
        f"AND vm.conversation_id={message_alias}.conversation_id "
        f"AND vm.joined_after_sequence<{message_alias}.sequence "
        f"AND (vm.left_at_sequence IS NULL OR vm.left_at_sequence>={message_alias}.sequence))"
    )


def can_observe(message: Message, membership: Membership, upper_sequence: int) -> bool:
    return (
        message.community_id == membership.community_id
        and message.conversation_id == membership.conversation_id
        and message.sequence <= upper_sequence
        and membership.covers(message.sequence)
        and membership.membership_id in message.audience
    )
