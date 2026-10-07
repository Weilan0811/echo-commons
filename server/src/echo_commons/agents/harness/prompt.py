from functools import cache
from importlib.resources import files

from echo_commons.agents.contracts.context import MemoryContext, SelfContext


@cache
def read_prompt_resource(name: str) -> str:
    return (
        files("echo_commons")
        .joinpath("resources", "prompts", name)
        .read_text(encoding="utf-8")
        .strip()
    )


def render_expression_guidance() -> str:
    return read_prompt_resource("common/expression.md")


def render_prompt_section(name: str, content: str) -> str:
    cleaned = _clean(content)
    if not cleaned:
        return ""
    return f"<{name}>\n{cleaned}\n</{name}>"


def _clean(value: str) -> str:
    return value.strip()


def render_persona(
    agent_contract: str, profile: str, relational_dynamics: str, voice: str | None = None
) -> tuple[tuple[str, str], ...]:
    shared = "全部输出都以角色本人的身份理解和表达，始终遵循角色的身份、记忆、能力与表达规则。"
    sections = (
        ("agent_contract", shared + "\n\n" + agent_contract.strip()),
        ("character_profile", profile),
        ("character_relational_dynamics", relational_dynamics),
    )
    return (*sections, ("character_voice", voice)) if voice is not None else sections


def render_identity(identity: SelfContext, *, include_voice: bool) -> tuple[tuple[str, str], ...]:
    return render_persona(
        identity.agent_contract,
        identity.profile,
        identity.relational_dynamics,
        identity.voice if include_voice else None,
    )


def render_state(identity: SelfContext) -> str:
    sentences = [
        {
            "available": "你现在有空，可以自然地回应对方。",
            "busy": "你手头还有自己的事情，但能分一点心思回应对方。",
            "offline": "你现在不在线，回应会显得断断续续。",
        }[identity.availability]
    ]
    for value, template in (
        (identity.physical_state, "身体状况是{}。"),
        (identity.mood, "心情是{}。"),
        (identity.activity, "手头正在做的是{}。"),
    ):
        if value.strip():
            sentences.append(template.format(value))
    return "你此刻的状态：\n" + " ".join(sentences)


def render_relationships(identity: SelfContext) -> str:
    descriptions = {
        "stranger": "你和对方目前还是陌生人。",
        "acquaintance": "你和对方已经是熟人。",
        "friend": "你和对方已经是朋友。",
    }
    return "\n\n".join(
        f"关系目标：{relation.target_name}（{relation.target.kind.value}:{relation.target.actor_id}）\n"
        + "你和对方现在的相处：\n"
        + " ".join(
            part
            for part in (descriptions[relation.relationship_type], relation.attitude.strip())
            if part
        )
        for relation in identity.relationships
    )


def render_memory(memory: MemoryContext) -> str:
    resident = render_memory_items(memory.resident, heading="你一直记得的一些事情：")
    digest = (
        "你对前面这段相处还留着这样的印象：\n" + memory.session_digest.strip()
        if memory.session_digest.strip()
        else ""
    )
    summaries = tuple("近期消息段摘要\n" + item.content for item in memory.segment_summaries)
    core = "你保留的核心记忆：\n" + memory.core_memory if memory.core_memory else ""
    state = "你对当前状态的概括：\n" + memory.state_summary if memory.state_summary else ""
    return "\n\n".join(part for part in (core, state, resident, digest, *summaries) if part)


def render_memory_items(items, *, heading: str) -> str:
    lines = [f"- {item.content.strip()}" for item in items if item.content.strip()]
    return heading + "\n" + "\n".join(lines) if lines else ""
