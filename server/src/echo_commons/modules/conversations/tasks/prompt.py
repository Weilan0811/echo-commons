from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    render_conversation_guidance,
    render_identity,
    render_memory,
    render_memory_items,
    render_output_contract,
    render_prompt_section,
    render_relationships,
    render_state,
)
from echo_commons.infrastructure.models.protocol import PromptMessage


def project_snapshot(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
) -> PromptContext:
    if not isinstance(snapshot, ContextSnapshot):
        raise ValueError("Conversation projector requires a conversation snapshot")
    outputs.schema(output_contract)
    messages = [
        PromptMessage(role="system", content=render_snapshot(snapshot, output_contract, outputs))
    ]
    for message in (*snapshot.perspective.history, *snapshot.perspective.inputs):
        own = (
            message.sender.kind == "character"
            and message.sender.actor_id == snapshot.scope.character_id
        )
        content = (
            message.text
            if own
            else (
                f"发送者：{message.sender_name}（{message.sender.kind.value}:{message.sender.actor_id}）\n"
                f"消息标识：{message.message_id}\n{message.text}"
            )
        )
        messages.append(PromptMessage(role="assistant" if own else "user", content=content))
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)


def render_snapshot(
    snapshot: ContextSnapshot, contract: OutputContractRef, outputs: OutputRegistry
) -> str:
    sections = [
        ("response_contract", render_output_contract(contract.schema_id)),
        ("conversation_guidance", render_conversation_guidance()),
        *render_identity(snapshot.self, include_voice=True),
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
            "是角色当时留下的私有内心片段；最后的 user 消息是本次需要回应的内容。",
        ),
    ]
    return "\n\n".join(
        render_prompt_section(name, content) for name, content in sections if content.strip()
    )
