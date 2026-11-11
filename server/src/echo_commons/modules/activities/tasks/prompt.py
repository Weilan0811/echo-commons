import json

from echo_commons.agents.contracts.activity import ActivityTurnInput
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import read_prompt_resource, render_prompt_section
from echo_commons.infrastructure.models.decision_protocol import ChoiceQuestion
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.activities.decisions import new_messages
from echo_commons.modules.activities.tasks.expression_prompt import expression_messages
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.conversations.tasks.prompt import (
    context_sections,
    conversation_messages,
    evidence_references,
)
from echo_commons.modules.social.judgment import participation_question
from echo_commons.shared.actors import ActorRef


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


def activity_messages(snapshot, *, decision=False, output_instructions=""):
    if snapshot.kind == "expression":
        return expression_messages(snapshot, output_instructions)
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
    shared = context_sections(common, expression_guidance=not decision)
    stable = {
        "character_identity",
        "agent_contract",
        "character_profile",
        "character_relational_dynamics",
        "character_voice",
        "conversation_guidance",
    }
    sections = [
        *(item for item in shared if item[0] in stable),
        (
            "activity_task",
            read_prompt_resource("activity/common.md")
            + "\n\n"
            + read_prompt_resource(f"activity/{snapshot.kind}.md")
            + ("\n\n" + read_prompt_resource("activity/decision.md") if decision else ""),
        ),
        ("output_contract", output_instructions),
        ("task_state", task_state(snapshot)),
        (
            "formal_observation",
            material.game.model_dump_json(
                include={
                    "occurred_at_utc",
                    "events",
                    "after_event_sequence",
                    "through_event_sequence",
                    "has_more_events",
                    "after_message_sequence",
                    "through_message_sequence",
                }
            ),
        ),
        *(
            item
            for item in shared
            if item[0] not in stable and item[0] != "conversation_participants"
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
    system = "\n\n".join(render_prompt_section(name, text) for name, text in sections if text)
    return (PromptMessage(role="system", content=system), *conversation_messages(common))


def task_state(snapshot):
    material = snapshot.material
    common = material.conversation
    session = (
        material.session_context.model_dump(mode="json")
        if material.session_context
        else {
            "game_id": snapshot.scope.game_id,
            "game_type": material.game.game_type,
            "self_participation_id": snapshot.scope.participation_id,
            "self_seat_id": snapshot.scope.seat_id,
            "rules": material.game.rules,
        }
    )
    if material.session_context:
        session["winners"] = [p.model_dump(mode="json") for p in material.session_context.winners]
    current = {
        "status": material.game.status,
        "state_version": material.game.state_version,
        "view": material.game.view.model_dump(mode="json", exclude={"opportunities"})
        if material.game.view
        else None,
    }
    if isinstance(snapshot, ActivityTurnInput):
        opportunity = snapshot.opportunity.model_dump(mode="json", exclude={"legal_actions"})
        actions = {}
        for action in snapshot.opportunity.legal_actions:
            parameters = action.model_dump(mode="json")
            action_type = parameters.pop("type")
            group = actions.setdefault(action_type, {"fields": list(parameters), "values": []})
            group["values"].append(list(parameters.values()))
        opportunity["legal_actions"] = actions
        current["opportunity"] = opportunity
    if snapshot.kind == "expression":
        current = snapshot.current_observation
    visible = {m.message_id for m in common.current_messages}
    communication = {
        "pending_message_ids": common.perspective.trigger_message_ids,
        "messages": [
            {
                "number": number,
                "message_id": m.message_id,
                "sender": m.model_dump(mode="json", include={"sender"})["sender"],
                "pending": m.message_id in common.perspective.trigger_message_ids,
            }
            for number, m in enumerate(common.current_messages, 1)
        ],
        "recent_self_message_ids": [
            m.message_id
            for m in common.current_messages
            if m.sender == ActorRef("character", snapshot.scope.character_id)
        ][-2:],
        "event_ids": [e.event_id for e in material.game.events],
        "expression_allowed": material.expression_allowed,
        "response_progress": [
            p.model_dump(mode="json", include={"message_ids", "status", "current"})
            for p in material.responses
            if p.current or p.status == "pending_expression" or visible.intersection(p.message_ids)
        ],
    }
    return "\n".join(
        render_prompt_section(name, content)
        for name, content in (
            ("session_context", json.dumps(session, ensure_ascii=False, separators=(",", ":"))),
            ("current_game_state", json.dumps(current, ensure_ascii=False, separators=(",", ":"))),
            ("current_intents", material.working_memory.model_dump_json()),
            (
                "communication_state",
                json.dumps(communication, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    )


def material_size(snapshot, *, decision=False):
    return sum(len(item.content) for item in activity_messages(snapshot, decision=decision))


def project_activity(
    snapshot, *, output_contract, outputs, tool_definitions=(), max_content_chars=None
):
    schema = json.dumps(outputs.schema(output_contract), ensure_ascii=False)
    messages = list(
        activity_messages(snapshot, output_instructions="只返回符合以下结构的 JSON：\n" + schema)
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
        if snapshot.origin is not None:
            refs += (f"activity_input:{snapshot.origin.input_id}",)
            refs += tuple(f"message:{identity}" for identity in snapshot.origin.message_ids)
            refs += tuple(f"game_event:{identity}" for identity in snapshot.origin.event_ids)
        refs += tuple(f"game_event:{identity}" for identity in snapshot.receipt_event_ids)
        if snapshot.phase != "before_action":
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
    refs += (f"activity_input:{snapshot.snapshot_id}",)
    messages[0] = messages[0].model_copy(
        update={
            "content": messages[0].content
            + "\n\n"
            + render_prompt_section(
                "evidence_sources",
                "expression.claims.evidence_refs 使用下列可引用来源编号；"
                + "understanding.message_id 和 intents.message_ids 继续使用真实消息编号：\n"
                + json.dumps(tuple(dict.fromkeys(refs)), ensure_ascii=False),
            )
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
    common = snapshot.material.conversation
    own = ActorRef("character", snapshot.scope.character_id)
    return {
        "角色与局势": messages[0].content,
        "聊天经过": [item.model_dump(mode="json") for item in messages[1:]],
        "新增来源": {
            "message_ids": [m.message_id for m in new_messages(snapshot)],
            "event_ids": list(
                dict.fromkeys(
                    (
                        *snapshot.material.reaction_event_ids,
                        *(e.event_id for e in snapshot.material.game.events),
                    )
                )
            ),
        },
        "交流判断依据": {
            "待回应消息": [
                {"message_id": m.message_id, "text": m.text}
                for m in common.current_messages
                if m.message_id in common.perspective.trigger_message_ids
            ],
            "近期本人发言": [
                {"message_id": m.message_id, "text": m.text}
                for m in common.current_messages
                if m.sender == own
            ][-2:],
            "已有交流安排": [
                p.model_dump(include={"message_ids", "status", "current"}, mode="json")
                for p in snapshot.material.responses
            ],
            "新增事件": [
                {"event_id": e.event_id, "type": e.type} for e in snapshot.material.game.events
            ],
            "当前意图": [
                i.model_dump(include={"intent_id", "content"}, mode="json")
                for i in snapshot.material.working_memory.intents
            ],
            "正在同时选择行动": snapshot.kind == "turn",
        },
    }


def decision_questions(snapshot):
    if snapshot.kind == "reply":
        question = participation_question()
        question = question.model_copy(
            update={
                "instructions": question.instructions
                + communication_instructions(choosing_action=False),
                "criteria": {
                    **question.criteria,
                    "participate": (
                        "对本次尚未回应的消息表达自己想说的新回应。"
                        if snapshot.material.conversation.perspective.trigger_message_ids
                        else "在本次交流安排下表达尚未说过、现在确实想补充的反应或想法。"
                    ),
                },
            }
        )
        questions = {"participation": question}
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
                instructions=communication_instructions(choosing_action=True),
                criteria={
                    **(
                        {"reply_messages": "对本次尚未回应的消息表达自己想说的新回应。"}
                        if snapshot.material.conversation.perspective.trigger_message_ids
                        else {}
                    ),
                    "comment_action": "表达这轮行动中尚未说过、现在确实想让同桌知道的打算或态度。",
                    **(
                        {"react_events": "对本次新事件表达尚未说过、确实想分享的新反应。"}
                        if snapshot.material.game.events or snapshot.material.reaction_event_ids
                        else {}
                    ),
                    "silent": "现在没有需要补充的新内容，我愿意安静地继续。",
                    "understand": "本次新语境的含义仍不清楚，需要进一步理解后决定是否开口。",
                },
                allow_none=False,
            ),
        }
    if snapshot.material.game.status == "running" and (
        new_messages(snapshot)
        or snapshot.material.game.events
        or snapshot.material.reaction_event_ids
    ):
        questions["intent_update"] = ChoiceQuestion(
            instructions=(
                "只针对新增来源，判断是否产生新的打算、约定或需要改写原意图。"
                "消息可能是打趣、挑衅或求情，结合语境和自身态度理解。"
                "普通行动进展、重复旧话和继续执行原意图选择 unchanged。"
                "现有意图的逐项去留另有问题；新增来源没有改变原打算时无需进一步理解。"
            ),
            criteria={
                "unchanged": "保留或结束原有意图，无需新增或改写。",
                "understand": "进一步理解新的打算或约定，决定是否修改原意图。",
            },
            allow_none=False,
        )
    if snapshot.material.game.status == "running":
        questions.update(
            {
                f"intent_{index}": ChoiceQuestion(
                    instructions=(
                        "判断这项原有局内意图是否仍然适用；"
                        "正常推进仍可沿用，目标已经完成或不再适用时结束。"
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


def communication_instructions(*, choosing_action):
    return (
        "你现在有没有值得说给同桌的新内容？阅读交流判断依据和完整经过，"
        "结合自己的性格与态度选择本次交流目的。"
        "先看待回应消息、近期自己的话和已有安排；已经回应或已安排表达的内容只作背景。"
        "普通落子、移动和继续原打算本身无需再解释；确有新的反应可以表达，"
        "没有需要补充的内容可以安静。"
        + (
            "行动问题还在同时选择，这里判断本轮交流价值，无需预想最终动作的具体细节。"
            if choosing_action
            else "本次只有交流安排，不选择游戏动作。"
        )
        + "只有新的话语或事件确实需要进一步理解时选择 understand。"
    )
