import json

from echo_commons.agents.harness.prompt import read_prompt_resource, render_prompt_section
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.conversations.tasks.prompt import context_sections, conversation_messages


def expression_messages(snapshot, output_instructions):
    material = snapshot.material
    common = material.conversation
    if material.session_context:
        resident = tuple(
            item
            for item in common.memory.resident
            if not (
                item.source_kind == "game_experience"
                and item.memory_id == snapshot.scope.participation_id
                and item.content_version == f"{material.game.state_version}:None"
            )
        )
        common = common.model_copy(
            update={"memory": common.memory.model_copy(update={"resident": resident})}
        )
    shared = context_sections(common, expression_guidance=True)
    stable = {
        "character_identity",
        "agent_contract",
        "character_profile",
        "character_relational_dynamics",
        "character_voice",
        "conversation_guidance",
    }
    decision = snapshot.origin.decision if snapshot.origin else {}
    initiations = snapshot.origin.initiations if snapshot.origin else ()
    events = {e.event_id: e for e in material.game.events}
    for source in initiations:
        events.update((e.event_id, e) for e in source.events)
    intents = (
        decision.get("intents")
        if snapshot.phase == "before_action" and decision.get("intents") is not None
        else material.working_memory.intents
    )
    targets = [
        {"content": i["content"], "message_ids": i.get("message_ids", ())}
        if isinstance(i, dict)
        else i.model_dump(include={"content", "message_ids"}, mode="json")
        for i in intents
    ]
    session = material.session_context
    identity = {
        "game_type": material.game.game_type,
        "self_seat_id": snapshot.scope.seat_id,
        "rules": material.game.rules,
    }
    if session:
        identity.update(
            participants=[
                p.model_dump(include={"actor", "display_name", "seat_id", "is_self"}, mode="json")
                for p in session.participants
            ],
            result=session.result,
        )
    observation = snapshot.current_observation
    view = observation.get("view") or {}
    state = {key: view[key] for key in ("phase", "state", "viewer_seat_id") if key in view}
    state["status"] = observation.get("status", material.game.status)
    communication = {
        "pending_message_ids": snapshot.origin.message_ids if snapshot.origin else (),
        "responses": [
            response.model_dump(include={"message_ids", "status", "current"}, mode="json")
            for response in material.responses
        ],
    }
    task_state = "\n".join(
        render_prompt_section(name, json.dumps(value, ensure_ascii=False))
        for name, value in (
            ("session_context", identity),
            ("current_game_state", state),
            ("current_intents", targets),
            ("communication_state", communication),
        )
    )
    sections = [
        *(part for part in shared if part[0] in stable),
        ("activity_task", read_prompt_resource("activity/expression.md")),
        ("output_contract", output_instructions),
        ("task_state", task_state),
        (
            "formal_observation",
            json.dumps(
                [
                    e.model_dump(
                        include={"event_id", "type", "data", "occurred_at_utc"}, mode="json"
                    )
                    for e in sorted(events.values(), key=lambda e: e.sequence)
                ],
                ensure_ascii=False,
            )
            if events
            else "",
        ),
        *(
            part
            for part in shared
            if part[0] not in stable and part[0] not in ("conversation_participants", "situation")
        ),
    ]
    # 新输入使用明确来源；已有冻结输入继续保留其原有情境材料。
    if snapshot.origin is None or "initiations" not in snapshot.origin.model_fields_set:
        sections.extend(part for part in shared if part[0] == "situation")
    task = expression_task(snapshot, decision, initiations)
    return (
        PromptMessage(
            role="system",
            content="\n\n".join(
                render_prompt_section(name, content) for name, content in sections if content
            ),
        ),
        *conversation_messages(common),
        PromptMessage(role="user", content=render_prompt_section("current_task", task)),
    )


def expression_task(snapshot, decision, initiations):
    subject = decision.get("subject", {})
    action = subject.get("action") or decision.get("action")
    speech = decision.get("speech", {})
    goal = speech.get("goal") or decision.get("expression_goal") or {}
    messages = snapshot.origin.message_ids if snapshot.origin else ()
    lines = ["这是运行层提供的本次表达任务。", f"你是{snapshot.scope.seat_id}席位的角色。"]
    reasons = []
    if action:
        reasons.append("自己的行动")
    if messages:
        reasons.append("待回应消息")
    labels = {
        "events": "游戏事件",
        "settlement": "对局结算",
        "quiet": "安静交流机会",
        "initiation": "主动交流安排",
    }
    reasons.extend(labels[source.kind] for source in initiations)
    if not reasons:
        reasons.append("已安排的局内交流")
    lines.append("本次来源：" + "、".join(dict.fromkeys(reasons)) + "。")
    lines.append(
        "交流目的：" + goal["purpose"] if goal.get("purpose") else "结合实际来源完成本次交流。"
    )
    if messages:
        lines.append("本次回应范围：" + json.dumps(messages, ensure_ascii=False))
    else:
        lines.append(
            "本次没有待回应的新消息。此前已完成回应的内容只作为背景；"
            "本次没有新增表达含义时，可以保持安静。"
        )
    for source in initiations:
        if source.situation:
            lines.append("本次情境：" + source.situation)
    if action:
        lines.append("已选行动：" + json.dumps(action, ensure_ascii=False))
    if snapshot.phase == "before_action":
        lines.append("动作尚未执行，正文会在动作成功后发表；只描述当前选择，不断定执行结果。")
    elif snapshot.receipt:
        lines.append("已有正式动作回执：" + json.dumps(snapshot.receipt, ensure_ascii=False))
    if snapshot.origin:
        lines.append("原判断时间：" + snapshot.origin.prepared_at_utc.isoformat())
    lines.extend(
        [
            "按聊天经过和这次目的表达值得补充的内容；没有适合补充的内容时，返回 expression=null。",
            "正文提到本次选定的动作或行动安排时，comments_on_action=true；"
            "只接话、不评论本次动作时填写 false。",
            "沿用提供的局内意图，不重新选择或执行动作。",
        ]
    )
    return "\n".join(lines)
