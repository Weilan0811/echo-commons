from collections import defaultdict

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.modules.memory.services.tokenization import tokenize_text
from echo_commons.shared.actors import ActorRef


class ContextBudgetExceeded(ValueError):
    def __init__(self, snapshot: ContextSnapshot) -> None:
        super().__init__("Persona and current input exceed configured context budget")
        self.snapshot = snapshot


class HistorySummaryRequired(ValueError):
    def __init__(self, snapshot, message_ids):
        super().__init__("Current conversation history requires a successful summary")
        self.snapshot = snapshot
        self.message_ids = tuple(message_ids)


def select_context(snapshot, max_size, measure):
    memory = snapshot.memory
    current_id = snapshot.scope.conversation_id
    base = snapshot.model_copy(
        update={
            "perspective": snapshot.perspective.model_copy(update={"history": ()}),
            "memory": memory.model_copy(
                update={
                    "resident": (),
                    "recalled": (),
                    "session_digest": "",
                    "history_thoughts": (),
                    "segment_summaries": (),
                }
            ),
        }
    )
    base_size = measure(base)
    if base_size > max_size:
        raise ContextBudgetExceeded(base)
    groups = [[], [], []]
    thoughts = {t.message_id: t for t in memory.history_thoughts}
    covered = set(memory.covered_message_ids)
    current = [m for m in reversed(snapshot.perspective.history) if m.conversation_id == current_id]
    summaries = sorted(memory.segment_summaries, key=lambda s: s.ended_at_utc, reverse=True)
    local_summaries = [
        s for s in summaries if any(c.conversation_id == current_id for c in s.conversations)
    ]
    groups[0].extend(("history", m) for m in current[:2])
    groups[0].extend(("segment_summaries", s) for s in local_summaries)
    groups[0].extend(("history", m) for m in current[2:])
    scenes = defaultdict(list)
    for message in reversed(snapshot.perspective.history):
        if message.conversation_id != current_id:
            scenes[message.conversation_id].append(("history", message))
    for summary in summaries:
        if summary not in local_summaries:
            scene_id = summary.conversations[0].conversation_id
            scenes[scene_id].append(("segment_summaries", summary))
    # 每个场景先取得一次机会，再依次补充细节，保留近期场景的连续影响。
    query = set(tokenize_text(memory.retrieval_query))
    actor = ActorRef("character", snapshot.scope.character_id)

    def significance(entry):
        field, item = entry
        timestamp = item.occurred_at_utc if field == "history" else item.ended_at_utc
        age = max(0, (snapshot.prepared_at_utc - timestamp).total_seconds())
        text = item.text if field == "history" else item.content
        relevance = len(query.intersection(tokenize_text(text))) / max(1, len(query))
        important = (
            0.25
            if field == "segment_summaries"
            else 0.25
            * (
                actor in item.mentions
                or item.sender == actor
                or item.reply_to_message_id is not None
            )
        )
        return 1 / (1 + age / 3600) + relevance + important

    ordered = sorted(scenes.values(), key=lambda items: max(map(significance, items)), reverse=True)
    for items in ordered:
        latest = max(
            items,
            key=lambda entry: (
                entry[1].occurred_at_utc if entry[0] == "history" else entry[1].ended_at_utc
            ),
        )
        items[:] = [
            latest,
            *sorted((i for i in items if i != latest), key=significance, reverse=True),
        ]
    while any(ordered):
        for items in ordered:
            if items:
                groups[1].append(items.pop(0))
    groups[2].extend(
        ("recalled", i)
        for i in sorted(memory.recalled, key=lambda i: i.source_kind != "memory_fact")
    )
    if memory.session_digest:
        groups[2].append(("session_digest", memory.session_digest))
    groups[1].extend(("resident", i) for i in memory.resident if i.source_kind == "game_experience")
    groups[2].extend(("resident", i) for i in memory.resident if i.source_kind != "game_experience")

    def add(value, field, item):
        if field == "history":
            history = tuple(
                sorted(
                    (*value.perspective.history, item),
                    key=lambda m: (m.occurred_at_utc, m.message_id),
                )
            )
            paired = (
                (*value.memory.history_thoughts, thoughts[item.message_id])
                if item.message_id in thoughts
                else value.memory.history_thoughts
            )
            return value.model_copy(
                update={
                    "perspective": value.perspective.model_copy(update={"history": history}),
                    "memory": value.memory.model_copy(update={"history_thoughts": paired}),
                }
            )
        content = item if field == "session_digest" else (*getattr(value.memory, field), item)
        return value.model_copy(update={"memory": value.memory.model_copy(update={field: content})})

    available = max_size - base_size
    shares = (
        memory.current_ratio,
        memory.nearby_ratio,
        1 - memory.current_ratio - memory.nearby_ratio,
    )
    selected, remaining = base, []
    for group, ratio in zip(groups, shares, strict=True):
        used, deferred = 0, []
        history_blocked = False
        for field, item in group:
            local = field == "history" and item.conversation_id == current_id
            candidate = add(selected, field, item)
            cost = measure(candidate) - measure(selected)
            if (
                not (local and history_blocked)
                and used + cost <= available * ratio
                and measure(candidate) <= max_size
            ):
                selected, used = candidate, used + cost
            else:
                deferred.append((field, item))
                history_blocked = history_blocked or local
        remaining.append(deferred)
    for group in remaining:
        history_blocked = False
        for field, item in group:
            local = field == "history" and item.conversation_id == current_id
            candidate = add(selected, field, item)
            if not (local and history_blocked) and measure(candidate) <= max_size:
                selected = candidate
            else:
                history_blocked = history_blocked or local
    selected_ids = {m.message_id for m in selected.perspective.history}
    missing = [
        m.message_id
        for m in reversed(current)
        if m.message_id not in selected_ids and m.message_id not in covered
    ]
    if missing:
        # 为摘要预留空间，连同较早的未归段历史一起整理，保留最近的交流原话。
        missing = list(
            dict.fromkeys(
                [
                    *(m.message_id for m in reversed(current[2:]) if m.message_id not in covered),
                    *missing,
                ]
            )
        )
        pending = snapshot.model_copy(
            update={
                "memory": memory.model_copy(
                    update={
                        "context_prepared": False,
                        "summary_message_ids": tuple(missing),
                    }
                )
            }
        )
        raise HistorySummaryRequired(pending, missing)
    # 已完成输入只保存实际使用的材料版本，历史归档继续由原所属记录保存。
    retained = {
        ("message", m.message_id)
        for m in (*selected.perspective.history, *selected.perspective.inputs)
    }
    retained.update(("thought", t.thought_id) for t in selected.memory.history_thoughts)
    retained.update(("segment_summary", s.segment_id) for s in selected.memory.segment_summaries)
    retained.update(
        (i.source_kind, i.memory_id) for i in (*selected.memory.resident, *selected.memory.recalled)
    )
    filtered_kinds = {
        "message",
        "thought",
        "segment_summary",
        "author_preload",
        *(i.source_kind for i in (*memory.recalled, *memory.resident)),
    }
    return selected.model_copy(
        update={
            "source_versions": tuple(
                v
                for v in selected.source_versions
                if v.kind not in filtered_kinds or (v.kind, v.source_id) in retained
            ),
            "memory": selected.memory.model_copy(
                update={
                    "context_prepared": True,
                    "summary_message_ids": (),
                    "covered_message_ids": tuple(sorted(covered & selected_ids)),
                }
            ),
        }
    )
