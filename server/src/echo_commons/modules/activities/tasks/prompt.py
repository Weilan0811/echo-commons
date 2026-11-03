import json

from echo_commons.agents.contracts.activity import ActivityTurnInput
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import read_prompt_resource, render_prompt_section
from echo_commons.infrastructure.models.decision_protocol import ChoiceQuestion
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.conversations.tasks.prompt import (
    context_sections,
    conversation_messages,
    evidence_references,
)
from echo_commons.modules.social.judgment import participation_question


def understanding_instructions(snapshot):
    return (
        "本次来源处理要求：understanding.messages 只记录以下消息编号，"
        "列表为空时返回 []。历史聊天继续作为背景。"
        "understanding.event_ids 完整填写以下事件编号。\n"
        + json.dumps(
            {
                "message_ids": snapshot.material.conversation.perspective.trigger_message_ids,
                "event_ids": tuple(e.event_id for e in snapshot.material.game.events),
            },
            ensure_ascii=False,
        )
    )


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
                    "pending_message_ids": common.perspective.trigger_message_ids,
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
            "expression_permission",
            "允许本次提出表达。"
            if material.expression_allowed
            else "当前没有新的交流名额，本次只完成行动与理解，expression 必须为 null。",
        ),
        (
            "response_progress",
            json.dumps(
                [item.model_dump(mode="json") for item in material.responses], ensure_ascii=False
            ),
        ),
    ]
    if "private_thoughts" in material.model_fields_set:
        sections.extend(
            [
                (
                    "own_private_thoughts",
                    json.dumps(
                        [item.model_dump(mode="json") for item in material.private_thoughts],
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
    if isinstance(snapshot, ActivityTurnInput):
        sections.append(("action_analysis", snapshot.analysis.model_dump_json()))
    if snapshot.kind == "expression":
        sections.extend(
            (
                ("expression_receipt", json.dumps(snapshot.receipt, ensure_ascii=False)),
                (
                    "current_observation",
                    json.dumps(snapshot.current_observation, ensure_ascii=False),
                ),
            )
        )
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
        update={"content": messages[0].content + "\n只返回符合以下结构的 JSON：\n" + schema}
    )
    common = snapshot.material.conversation
    refs = tuple(
        f"message:{m.message_id}"
        for m in (
            *common.perspective.inputs,
            *common.perspective.history,
        )
    )
    refs += tuple(f"game_event:{e.event_id}" for e in snapshot.material.game.events)
    refs += tuple(f"game_event:{identity}" for identity in snapshot.material.reaction_event_ids)
    if snapshot.kind == "expression":
        refs += tuple(f"game_event:{identity}" for identity in snapshot.receipt_event_ids)
        refs += (snapshot.snapshot_id.replace("expression:", "activity_result:", 1),)
        if snapshot.receipt:
            refs += (f"game_action:{snapshot.receipt['receipt_id']}",)
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
    refs += evidence_references(common)
    messages[0] = messages[0].model_copy(
        update={
            "content": messages[0].content
            + "\n\nexpression.claims.evidence_refs 使用下列可引用来源编号；"
            + "understanding.message_id 和 intents.message_ids 继续使用真实消息编号：\n"
            + json.dumps(tuple(dict.fromkeys(refs)), ensure_ascii=False)
        }
    )
    size = sum(len(item.content) for item in messages) + len(
        json.dumps(tool_definitions, ensure_ascii=False)
    )
    if max_content_chars is not None and size > max_content_chars:
        raise ContextBudgetExceeded(common)
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


def decision_questions(snapshot):
    if snapshot.kind == "reply":
        questions = {"participation": participation_question()}
    else:
        questions = {
            "action": ChoiceQuestion(
                instructions=(
                    "结合自己的态度、局势、聊天和本局意图选择动作。"
                    "需要开放理解、候选之外的建议或新约定时选择 understand。"
                ),
                criteria={
                    **{
                        c.candidate_id: c.action.model_dump_json()
                        for c in snapshot.analysis.candidates
                    },
                    "understand": "进一步理解后再选择行动",
                },
                allow_none=False,
            ),
            "expression": ChoiceQuestion(
                instructions=(
                    "判断是否想交流。此问题独立于动作选择，只能依据当前局势、候选后果或条件，"
                    "不能假定已知道选中的动作。参考已有回应进度，避免为相同来源重复安排表达。"
                ),
                criteria={
                    "express": "想交流，之后根据真实行动生成正文",
                    "silent": "保持安静",
                    "understand": "需要进一步理解交流内容",
                },
                allow_none=False,
            ),
        }
    if snapshot.material.game.status == "running":
        questions["intent_update"] = ChoiceQuestion(
            instructions=(
                "结合聊天语境、自己的态度和当前打算，判断是否需要新增或改写本局意图。"
                "现有意图的逐项去留另有问题。独立判断，依据当前材料决定。"
            ),
            criteria={
                "unchanged": "保留或结束原有意图，无需新增或改写。",
                "understand": "进一步理解新的打算或约定，决定是否修改原意图。",
            },
            allow_none=False,
        )
        questions.update(
            {
                f"intent_{index}": ChoiceQuestion(
                    instructions=(
                        "判断这项原有局内意图是否仍然适用；"
                        "需要新增或修改时在 intent_update 选择进一步理解。"
                    ),
                    criteria={"keep": intent.content, "end": "结束这项意图"},
                    allow_none=False,
                )
                for index, intent in enumerate(snapshot.material.working_memory.intents)
            }
        )
    if not snapshot.material.expression_allowed and "expression" in questions:
        questions["expression"] = ChoiceQuestion(
            instructions="当前没有新的交流名额，完成行动并保持安静。",
            criteria={"silent": "保持安静"},
            allow_none=False,
        )
    return questions
