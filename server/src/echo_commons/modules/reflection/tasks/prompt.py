import json
from dataclasses import asdict

from pydantic import TypeAdapter

from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestAction,
    GraphExtractionAction,
    LongTermMemoryPageAction,
    NoOpReflectionAction,
    RelationshipReflectionAction,
    SegmentSummaryAction,
    StateReflectionAction,
)
from echo_commons.modules.reflection.contracts.context import ReflectionNodeInput
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind

_NODE_INSTRUCTIONS = {
    ReflectionNodeKind.SEGMENT_SUMMARY_PLAN: "整理本记忆段，输出 segment_summary 与 follow_up。"
    "根据真实材料决定是否需要进一步分析关系与自身状态。",
    ReflectionNodeKind.RELATIONSHIP_REFLECT: (
        "输出 relationship_reflection，明确填写每个目标的 target。"
        "仅建议当前材料支持的关系变化，按目标与维度分别处理。不要填写自己作为目标。"
    ),
    ReflectionNodeKind.STATE_REFLECT: "输出 state_reflection，填写当前材料支持的自身状态变化。",
    ReflectionNodeKind.CONTINUITY_COMPRESS: "输出 continuity_digest，综合前一摘要和本批段摘要。"
    "covers_through_sequence 填写本批最后一段的 last_sequence。",
    ReflectionNodeKind.PAGE_COMPOSE: (
        "输出 long_term_memory_page，整理有长期价值的事实、事件、偏好、承诺和未完成事项。"
    ),
    ReflectionNodeKind.GRAPH_EXTRACT: "输出 graph_extraction，提取材料支持的实体与关联。",
}

_OUTPUT_TYPES = {
    ReflectionNodeKind.SEGMENT_SUMMARY_PLAN: SegmentSummaryAction,
    ReflectionNodeKind.RELATIONSHIP_REFLECT: RelationshipReflectionAction,
    ReflectionNodeKind.STATE_REFLECT: StateReflectionAction,
    ReflectionNodeKind.CONTINUITY_COMPRESS: ContinuityDigestAction,
    ReflectionNodeKind.PAGE_COMPOSE: LongTermMemoryPageAction,
    ReflectionNodeKind.GRAPH_EXTRACT: GraphExtractionAction,
}


def project_node(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
) -> PromptContext:
    if not isinstance(snapshot, ReflectionNodeInput):
        raise ValueError("Reflection projector requires a reflection node input")
    graph = snapshot.graph_snapshot
    instruction = _NODE_INSTRUCTIONS[snapshot.node_kind]
    messages = (
        "根据当前角色的观察、内部状态和自身记忆完成反思。材料保留实际发送者身份。",
        instruction,
        "仅返回完整 JSON，结构如下：\n"
        + json.dumps(
            TypeAdapter(_OUTPUT_TYPES[snapshot.node_kind] | NoOpReflectionAction).json_schema(),
            ensure_ascii=False,
        ),
        "没有材料支持的变化时，可以输出 no_op 并说明 reason。"
        "evidence_refs 仅引用下列允许的来源。先使用给出的材料，需要补充过去记忆时才调用只读工具。",
        "有实际内容的结果必须填写 evidence_refs，引用支持该结果的具体材料。",
        "允许的来源：\n"
        + json.dumps(
            [material.evidence_ref for material in graph.materials]
            + [f"artifact:{artifact.artifact_id}" for artifact in snapshot.artifacts],
            ensure_ascii=False,
        ),
        "当前角色自身信息：\n" + graph.self.model_dump_json(),
        "关系反思允许的目标：\n"
        + json.dumps(
            [
                asdict(actor)
                for actor in sorted(
                    source_actors(graph), key=lambda actor: (actor.kind.value, actor.actor_id)
                )
            ],
            ensure_ascii=False,
        ),
        "自身记忆：\n" + graph.memory.model_dump_json(),
        "客观环境：\n" + graph.environment.model_dump_json(),
        "可见公共信息：\n" + json.dumps(graph.public_facts, ensure_ascii=False),
        "冻结的来源材料：\n"
        + json.dumps(
            [material.model_dump(mode="json") for material in graph.materials],
            ensure_ascii=False,
        ),
        "前驱节点的已完成产物：\n"
        + json.dumps(
            [artifact.model_dump(mode="json") for artifact in snapshot.artifacts],
            ensure_ascii=False,
        ),
    )
    return PromptContext(
        messages=(
            PromptMessage(role="system", content="\n\n".join(messages[:5])),
            PromptMessage(role="user", content="\n\n".join(messages[5:])),
        ),
        tool_definitions=tool_definitions,
    )
