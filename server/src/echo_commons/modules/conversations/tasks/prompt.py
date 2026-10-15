from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    read_prompt_resource,
    render_expression_guidance,
    render_identity,
    render_memory,
    render_memory_items,
    render_prompt_section,
    render_relationships,
    render_state,
)
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.shared.message_sources import message_source_id


def render_conversation_guidance() -> str:
    return render_expression_guidance() + "\n\n" + read_prompt_resource("conversation/guidance.md")


def project_snapshot(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
    max_content_chars: int | None = None,
) -> PromptContext:
    if not isinstance(snapshot, ContextSnapshot):
        raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
    outputs.schema(output_contract)
    messages = [
        PromptMessage(role="system", content=render_snapshot(snapshot, output_contract, outputs))
    ]
    thoughts = {thought.message_id: thought.content for thought in snapshot.memory.history_thoughts}
    all_messages = (*snapshot.perspective.history, *snapshot.perspective.inputs)
    names = {}
    for message in all_messages:
        names.setdefault(message.sender_name, set()).add(
            (message.sender.kind.value, message_source_id(message.sender))
        )
    aliases = {
        identity: name if len(identities) == 1 else f"{name}（{index}）"
        for name, identities in names.items()
        for index, identity in enumerate(sorted(identities), 1)
    }

    def text(message):
        identity = (message.sender.kind.value, message_source_id(message.sender))
        content = f"{message.occurred_at_utc:%m-%d %H:%M} {aliases[identity]}：{message.text}"
        reply = next(
            (item for item in all_messages if item.message_id == message.reply_to_message_id), None
        )
        if reply:
            content += f"\n回应：{reply.sender_name}说的“{reply.text[:80]}”"
        if message.mentions:
            mentioned = [
                aliases.get((actor.kind.value, actor.actor_id)) for actor in message.mentions
            ]
            if any(mentioned):
                content += "\n提及：" + "、".join(name for name in mentioned if name)
        if message.visibility == "仅指定受众可见":
            content += "\n范围：仅原指定受众可见"
        if message.message_id in thoughts:
            content += "\n自身私有念头：" + thoughts[message.message_id]
        return content

    for scene in snapshot.scope.conversations:
        if scene.conversation_id == snapshot.scope.conversation_id:
            continue
        history = sorted(
            (
                message
                for message in snapshot.perspective.history
                if message.conversation_id == scene.conversation_id
            ),
            key=lambda message: (message.occurred_at_utc, message.message_id),
        )
        if history:
            messages.append(
                PromptMessage(
                    role="system",
                    content="其他近期经历："
                    + scene.name
                    + ("｜私人交流" if scene.kind == "direct" else "｜群内交流")
                    + "｜仅供理解背景\n"
                    + "\n".join(text(message) for message in history),
                )
            )
    current = sorted(
        (
            message
            for message in all_messages
            if message.conversation_id == snapshot.scope.conversation_id
        ),
        key=lambda message: message.sequence,
    )
    for message in current:
        own = (
            message.sender.kind == "character"
            and message.sender.actor_id == snapshot.scope.character_id
        )
        messages.append(PromptMessage(role="assistant" if own else "user", content=text(message)))
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)


def render_snapshot(
    snapshot: ContextSnapshot, contract: OutputContractRef, outputs: OutputRegistry
) -> str:
    sections = [
        ("response_contract", read_prompt_resource("conversation/output.md")),
        *render_identity(snapshot.self, include_voice=True),
        ("conversation_guidance", render_conversation_guidance()),
        ("current_state", render_state(snapshot.self)),
        ("relationship_state", render_relationships(snapshot.self)),
        ("continuity_memory", render_memory(snapshot.memory)),
        (
            "recalled_memory",
            render_memory_items(
                snapshot.memory.recalled, heading="此刻从更远处浮现出来的一些记忆："
            ),
        ),
        (
            "situation",
            "眼前的情境：\n你注意到：\n"
            + "\n".join(f"- {fact}" for fact in snapshot.perspective.public_facts)
            if snapshot.perspective.public_facts
            else "",
        ),
        (
            "conversation_history",
            "下面的 user 和 assistant 消息属于当前会话。其他场景单独作为背景。自身私有念头 "
            "是角色当时留下的私有内心片段。实际发送者由消息中的身份字段说明。\n"
            "本次触发消息："
            + "、".join(
                snapshot.perspective.trigger_message_ids
                or tuple(message.message_id for message in snapshot.perspective.inputs)
            )
            + "\n本次交流的原始玩家输入："
            + ("、".join(snapshot.perspective.root_message_ids) or "见本次输入")
            + "。其余内容用于理解已经发生的交流；执行附加要求不属于聊天消息。",
        ),
    ]
    return "\n\n".join(
        render_prompt_section(name, content) for name, content in sections if content.strip()
    )
