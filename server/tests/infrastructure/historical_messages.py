from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.modules.conversations.domain.message import Message, MessageVisibility
from echo_commons.shared.actors import ActorRef


def historical_message(
    system, text="一起讨论", *, player="alice", client=None, recipients, mentions=(), reply=None
):
    # 准备旧版本保存的真实记录，供历史读取、索引和待执行任务验证使用。
    intake = system.intake
    sender = ActorRef("player", player)
    with intake.database.transaction() as connection:
        now = datetime.now(UTC)
        members = intake.conversations.members(connection, "conversation")
        membership = intake.conversations.current(connection, "conversation", sender)
        audience = tuple(
            sorted(
                member.membership_id for member in members if member.actor in {sender, *recipients}
            )
        )
        assert len(audience) == len(set(recipients) | {sender})
        message = Message(
            str(uuid4()),
            "community",
            "conversation",
            intake.conversations.allocate_sequence(connection, "conversation", now),
            sender,
            membership.membership_id,
            text,
            MessageVisibility.RECIPIENTS,
            audience,
            mentions,
            reply,
            client or text,
            None,
            None,
            str(uuid4()),
            now,
        )
        intake.messages.add(connection, message)
        intake.batches.collect(connection, message, intake.quiet_seconds)
        intake.indexer.message(connection, message)
    return message


def historical_receipt(client, identity, text=None, *, character="first", player="alice"):
    message = historical_message(
        client.app.state.application,
        text or identity,
        player=player,
        client=identity,
        recipients=(ActorRef("character", character),),
    )
    return {
        "message_id": message.message_id,
        "conversation_id": message.conversation_id,
        "sequence": message.sequence,
        "trace_id": message.trace_id,
    }
