import json
from zoneinfo import ZoneInfo

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    OutputRegistry,
    compact_schema,
)
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    read_prompt_resource,
    render_environment,
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
    messages.extend(conversation_messages(snapshot))
    refs = evidence_references(snapshot)
    if output_contract == CHARACTER_EXPRESSION_CONTRACT:
        messages[0] = messages[0].model_copy(
            update={
                "content": messages[0].content
                + "\n\n"
                + render_prompt_section(
                    "evidence_sources",
                    "本次可引用来源编号：\n" + json.dumps(refs, ensure_ascii=False),
                )
            }
        )
    return PromptContext(
        messages=tuple(messages), tool_definitions=tool_definitions, evidence_refs=refs
    )


def evidence_references(snapshot: ContextSnapshot) -> tuple[str, ...]:
    refs = [f"chat:{number}" for number in range(1, len(snapshot.current_messages) + 1)]
    refs.extend(
        f"history:{message.message_id}"
        for message in snapshot.perspective.history
        if message.conversation_id != snapshot.scope.conversation_id
    )
    refs.extend(
        f"{item.source_kind}:{item.memory_id}"
        for item in (*snapshot.memory.resident, *snapshot.memory.recalled)
        if item.content.strip()
    )
    refs.extend(("identity:profile", "identity:voice", "identity:relational_dynamics"))
    refs.extend(
        f"relationship:{item.target.kind.value}:{item.target.actor_id}"
        for item in snapshot.self.relationships
    )
    refs.extend(f"segment_summary:{item.segment_id}" for item in snapshot.memory.segment_summaries)
    for ref, value in (
        ("memory:core", snapshot.memory.core_memory),
        ("memory:continuity", snapshot.memory.session_digest),
        ("memory:state", snapshot.memory.state_summary),
        ("community:world", snapshot.environment.world_description),
        ("community:rules", snapshot.environment.community_rules),
    ):
        if value:
            refs.append(ref)
    return tuple(dict.fromkeys(refs))


def conversation_messages(snapshot: ContextSnapshot) -> tuple[PromptMessage, ...]:
    messages = []
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
        local_time = message.occurred_at_utc.astimezone(ZoneInfo(snapshot.environment.timezone))
        content = (
            f"{local_time:%m-%d %H:%M} {name(message.sender, message.sender_name)}：{message.text}"
        )
        if number is not None:
            content += f"[{number}]"
        elif message.conversation_id != snapshot.scope.conversation_id:
            content += f" [history:{message.message_id}]"
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
    return tuple(messages)


def render_snapshot(
    snapshot: ContextSnapshot, contract: OutputContractRef, outputs: OutputRegistry
) -> str:
    checked = contract == CHARACTER_EXPRESSION_CONTRACT
    instructions = read_prompt_resource(
        "conversation/expression-output.md" if checked else "conversation/output.md"
    )
    if checked:
        schema = outputs.schema(contract)

        instructions += "\n\n输出字段结构：\n" + json.dumps(
            compact_schema(schema), ensure_ascii=False
        )
    sections = [
        ("response_contract", instructions),
        *context_sections(snapshot, expression_guidance=True),
        (
            "conversation_task",
            read_prompt_resource("conversation/initiation.md")
            if snapshot.scope.initiation_id
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


def context_sections(
    snapshot: ContextSnapshot, *, expression_guidance: bool = False
) -> list[tuple[str, str]]:
    situation = "\n".join(
        part
        for part in (
            "你注意到：\n" + "\n".join(f"- {fact}" for fact in snapshot.perspective.public_facts)
            if snapshot.perspective.public_facts
            else "",
            snapshot.perspective.situation,
        )
        if part
    )
    return [
        *render_identity(snapshot.self, include_voice=True),
        *(
            [("conversation_guidance", render_conversation_guidance())]
            if expression_guidance
            else []
        ),
        ("community_environment", render_environment(snapshot.environment)),
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
            "眼前的情境：\n" + situation if situation else "",
        ),
    ]


def participation_material(snapshot: ContextSnapshot) -> dict[str, object]:
    return {
        "角色及眼前情景": "\n\n".join(
            render_prompt_section(name, content)
            for name, content in context_sections(snapshot)
            if content.strip()
        ),
        "聊天经过": [
            message.model_dump(mode="json") for message in conversation_messages(snapshot)
        ],
    }
