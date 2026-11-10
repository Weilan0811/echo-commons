import json


def seat_name(identity):
    return {
        "black": "黑方",
        "white": "白方",
        "red": "红方",
        "yellow": "黄方",
        "green": "绿方",
        "blue": "蓝方",
    }.get(identity, f"席位{identity}")


def describe_event(data):
    data = data.model_dump(mode="json")
    kind = data["type"]
    if kind == "game_created":
        return f"{data['creator_ref']}创建了{data['game_type']}对局。"
    if kind == "participant_joined":
        person = data["participation"]
        return f"{person['participant_ref']}加入{seat_name(person['seat_id'])}。"
    if kind in ("participant_left", "participant_resigned"):
        action = "离开对局" if kind == "participant_left" else "认输"
        return f"{seat_name(data['seat_id'])}{action}（参与编号{data['participation_id']}）。"
    if kind == "game_started":
        return "对局开始。"
    if kind == "game_cancelled":
        return f"对局取消，记录的原因：{data['reason']}。"
    if kind == "game_finished":
        return "对局结束，正式结果：" + json.dumps(data["result"], ensure_ascii=False)
    seat = seat_name(data["seat_id"])
    if kind == "stone_placed":
        return f"{seat}落子({data['x']},{data['y']})。"
    if kind == "dice_rolled":
        return f"{seat}掷出{data['dice']}点。"
    if kind.startswith("plane_") or kind == "move_ended":
        plane = f"{seat}{data['plane_id']}号飞机"
        if kind == "plane_took_off":
            return plane + "起飞。"
        if kind == "plane_sent_back":
            reason = "因碰撞" if data["reason"] == "captured" else "因规则惩罚"
            return plane + reason + "返回机场。"
        if kind == "move_ended":
            return plane + "结束本次移动。"
        action = {"plane_walked": "移动", "plane_jumped": "跳跃", "plane_flew": "飞行"}[kind]
        return f"{plane}从进度{data['from_step']}{action}到{data['to_step']}。"
    if kind == "domino_placed":
        return f"{seat}放置{data['domino_id']}号地块：" + json.dumps(
            data["cells"], ensure_ascii=False
        )
    action = {
        "initial_king_placed": "将初始国王放在",
        "domino_chosen": "选择",
        "domino_discarded": "弃置",
    }[kind]
    return f"{seat}{action}{data['domino_id']}号地块。"
