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
from echo_commons.shared.actors import ActorRef


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
    known_names = {
        ActorRef("character", snapshot.scope.character_id): snapshot.self.name,
        **{item.target: item.target_name for item in snapshot.self.relationships},
    }
    for message in all_messages:
        if isinstance(message.sender, ActorRef):
            known_names[message.sender] = message.sender_name
        known_names.update(zip(message.mentions, message.mention_names, strict=False))
    own_actor = ActorRef("character", snapshot.scope.character_id)

    def name(sender, public_name):
        return f"{public_name}（你）" if sender == own_actor else public_name

    def text(message, number=None):
        content = (
            f"{message.occurred_at_utc:%m-%d %H:%M} "
            f"{name(message.sender, message.sender_name)}：{message.text}"
        )
        if number is not None:
            content += f"[{number}]"
        reply = next(
            (item for item in all_messages if item.message_id == message.reply_to_message_id), None
        )
        if reply:
            reply_name = name(reply.sender, reply.sender_name)
            content += f"\n回应：{reply_name}说的“{reply.text[:80]}”"
        if message.mentions:
            content += "\n提及：" + "、".join(
                name(actor, known_names.get(actor, actor.actor_id)) for actor in message.mentions
            )
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
    for number, message in enumerate(snapshot.current_messages, 1):
        own = (
            message.sender.kind == "character"
            and message.sender.actor_id == snapshot.scope.character_id
        )
        messages.append(
            PromptMessage(role="assistant" if own else "user", content=text(message, number))
        )
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
            "是角色当时留下的私有内心片段。实际发送者由消息中的称呼说明。"
            "结合按顺序提供的交流理解眼前话题；执行附加要求不属于聊天消息。",
        ),
    ]
    return "\n\n".join(
        render_prompt_section(name, content) for name, content in sections if content.strip()
    )
