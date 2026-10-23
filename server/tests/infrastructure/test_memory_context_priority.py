from support.social import build_planning_system, send

from echo_commons.agents.contracts.context import MemoryContext, MemoryItem
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.modules.conversations.tasks.memory import budget_snapshot
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.domain.policy import RetrievalPolicy
from echo_commons.modules.memory.services.retrieval import SearchHit
from echo_commons.shared.actors import ActorRef


def test_automatic_selection_prioritizes_matching_facts_and_respects_budget(tmp_path):
    system = build_planning_system(tmp_path)
    system.retrieval.policy = RetrievalPolicy(automatic_limit=2, automatic_max_chars=100)
    hits = (
        SearchHit("message", "question", "1", "早餐吃了什么？", "conversation"),
        SearchHit("memory_cognition", "opinion", "1", "早饭还是坐下来慢慢吃好。", None),
        SearchHit("memory_fact", "meal", "1", "小槿今天早餐吃了三明治，没有喝牛奶。", None),
        SearchHit("memory_fact", "duplicate", "1", "小槿今天早餐吃了三明治，没有喝牛奶。", None),
    )
    selected = system.retrieval.select_automatic(hits, set())
    assert tuple(hit.source_id for hit in selected) == ("meal", "question")
    assert system.retrieval.select_automatic(hits, {hits[2].text}) == hits[:2]


def test_context_budget_keeps_relevant_fact_after_general_background(tmp_path):
    system = build_planning_system(tmp_path)
    send(system, "你今天早餐喝了牛奶吧？", mentions=(ActorRef("character", "first"),))
    system.planner.plan()
    with system.database.read() as connection:
        task = connection.execute(
            "SELECT task_id FROM conversation_tasks WHERE character_id='first'"
        ).fetchone()[0]
        snapshot = system.tasks.snapshot(connection, task)
    fact = MemoryItem(
        memory_id="meal",
        source_kind="memory_fact",
        content_version="1",
        content="我今天早餐吃了三明治，没有喝牛奶。",
    )
    general = MemoryItem(
        memory_id="general",
        source_kind="author_preload",
        content_version="1",
        content="我喜欢整理旧物和喝热茶。" * 40,
    )
    current = snapshot.model_copy(
        update={
            "memory": MemoryContext(resident=(general,), recalled=(fact,), retrieval_prepared=True)
        }
    )
    minimum = current.model_copy(
        update={"memory": current.memory.model_copy(update={"resident": ()})}
    )
    registry = OutputRegistry()
    registry.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    max_chars = sum(
        len(message.content)
        for message in project_snapshot(
            minimum, output_contract=CHARACTER_MESSAGE_CONTRACT, outputs=registry
        ).messages
    )
    final = budget_snapshot(current, max_chars)
    assert final.memory.recalled == (fact,)
    assert final.memory.resident == ()
    assert final.perspective.inputs == current.perspective.inputs
    assert final.self == current.self
