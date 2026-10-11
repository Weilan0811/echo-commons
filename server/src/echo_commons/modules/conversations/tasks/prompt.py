import json

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
    for message in sorted(
        (*snapshot.perspective.history, *snapshot.perspective.inputs),
        key=lambda item: item.sequence,
    ):
        own = (
            message.sender.kind == "character"
            and message.sender.actor_id == snapshot.scope.character_id
        )
        metadata = (
            f"发送者：{message.sender_name}（{message.sender.kind.value}:"
            f"{message_source_id(message.sender)}）\n"
            f"消息标识：{message.message_id}\n"
            "提及对象："
            + (
                "、".join(f"{actor.kind.value}:{actor.actor_id}" for actor in message.mentions)
                or "无"
            )
            + "\n"
            f"回复来源：{message.reply_to_message_id or '无'}\n"
        )
        content = metadata + "\n正文：\n" + message.text
        if own and message.message_id in thoughts:
            content = metadata + json.dumps(
                {"thought": thoughts[message.message_id], "utterance": message.text},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        messages.append(PromptMessage(role="assistant" if own else "user", content=content))
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
            "下面的 user 和 assistant 消息是已经发生的对话。assistant 消息中的 thought "
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
