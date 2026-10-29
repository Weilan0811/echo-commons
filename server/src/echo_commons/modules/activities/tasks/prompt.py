import json

from echo_commons.agents.contracts.activity import ActivityTurnInput
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import read_prompt_resource, render_prompt_section
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.conversations.tasks.prompt import context_sections, conversation_messages


def activity_messages(snapshot, *, decision=False):
    material = snapshot.material
    common = material.conversation
    if decision:
        persona = material.decision_persona
        common = common.model_copy(
            update={
                "self": common.self.model_copy(
                    update={
                        "profile": persona.profile,
                        "voice": persona.voice,
                        "relational_dynamics": persona.relational_dynamics,
                    }
                )
            }
        )
    sections = [
        (
            "activity_task",
            read_prompt_resource("activity/common.md")
            + "\n\n"
            + read_prompt_resource(f"activity/{snapshot.kind}.md")
            + ("\n\n" + read_prompt_resource("activity/decision.md") if decision else ""),
        ),
        *context_sections(common, expression_guidance=not decision),
        (
            "current_input_sources",
            json.dumps(
                {
                    "messages": [
                        {
                            "number": number,
                            "message_id": message.message_id,
                            "pending": message.message_id in common.perspective.trigger_message_ids,
                        }
                        for number, message in enumerate(common.current_messages, 1)
                    ],
                    "event_ids": [e.event_id for e in material.game.events],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
        (
            "game_observation",
            json.dumps(
                {
                    "game_id": snapshot.scope.game_id,
                    "participation_id": snapshot.scope.participation_id,
                    "seat_id": snapshot.scope.seat_id,
                    **material.game.model_dump(mode="json", exclude={"view"}),
                    "view": None
                    if material.game.view is None
                    else material.game.view.model_dump(mode="json", exclude={"opportunities"}),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
        ("local_working_memory", material.working_memory.model_dump_json()),
        (
            "own_private_thoughts",
            json.dumps(
                [item.model_dump(mode="json") for item in material.private_thoughts],
                ensure_ascii=False,
            ),
        ),
    ]
    if isinstance(snapshot, ActivityTurnInput):
        sections.append(("action_analysis", snapshot.analysis.model_dump_json()))
    system = "\n\n".join(render_prompt_section(name, text) for name, text in sections if text)
    return (PromptMessage(role="system", content=system), *conversation_messages(common))


def material_size(snapshot, *, decision=False):
    return sum(len(item.content) for item in activity_messages(snapshot, decision=decision))


def project_activity(
    snapshot, *, output_contract, outputs, tool_definitions=(), max_content_chars=None
):
    messages = list(activity_messages(snapshot))
    schema = json.dumps(outputs.schema(output_contract), ensure_ascii=False)
    messages[0] = messages[0].model_copy(
        update={"content": messages[0].content + "\n输出结构：\n" + schema}
    )
    size = sum(len(item.content) for item in messages) + len(
        json.dumps(tool_definitions, ensure_ascii=False)
    )
    if max_content_chars is not None and size > max_content_chars:
        raise ContextBudgetExceeded(snapshot.material.conversation)
    common = snapshot.material.conversation
    refs = tuple(
        f"message:{m.message_id}"
        for m in (
            *common.perspective.inputs,
            *common.perspective.history,
        )
    )
    refs += tuple(f"game_event:{e.event_id}" for e in snapshot.material.game.events)
    refs += tuple(
        f"{m.source_kind}:{m.memory_id}"
        for m in (
            *common.memory.resident,
            *common.memory.recalled,
        )
    )
    refs += tuple(f"activity_input:{t.input_id}" for t in snapshot.material.private_thoughts)
    refs += tuple(f"thought:{t.thought_id}" for t in common.memory.history_thoughts)
    refs += tuple(f"segment_summary:{s.segment_id}" for s in common.memory.segment_summaries)
    return PromptContext(
        messages=tuple(messages),
        tool_definitions=tool_definitions,
        evidence_refs=tuple(dict.fromkeys(refs)),
    )


def decision_material(snapshot):
    messages = activity_messages(snapshot, decision=True)
    return {
        "角色与局势": messages[0].content,
        "聊天经过": [item.model_dump(mode="json") for item in messages[1:]],
    }
