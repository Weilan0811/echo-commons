from dataclasses import dataclass

from echo_commons.agents.harness.prompt import (
    render_identity,
    render_memory,
    render_relationships,
    render_state,
)
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.context import (
    ReflectionMaterial,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind


@dataclass(frozen=True, slots=True)
class NodePromptProjection:
    identity_sections: tuple[tuple[str, str], ...]
    state: str
    relationships: str
    memory: str
    materials: tuple[ReflectionMaterial, ...]

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(material.evidence_ref for material in self.materials)


def project_node_input(node: ReflectionNodeInput) -> NodePromptProjection:
    graph, kind = node.graph_snapshot, node.node_kind
    state_nodes = {ReflectionNodeKind.SEGMENT_SUMMARY_PLAN, ReflectionNodeKind.STATE_REFLECT}
    relationship_nodes = {
        ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
        ReflectionNodeKind.RELATIONSHIP_REFLECT,
    }
    memory_nodes = {
        ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
        ReflectionNodeKind.CONTINUITY_COMPRESS,
        ReflectionNodeKind.PAGE_COMPOSE,
        ReflectionNodeKind.GRAPH_EXTRACT,
        ReflectionNodeKind.CORE_MEMORY_VIEW,
    }
    material_kinds = {
        ReflectionNodeKind.SEGMENT_SUMMARY_PLAN: {"message", "thought"},
        ReflectionNodeKind.RELATIONSHIP_REFLECT: {"message", "thought"},
        ReflectionNodeKind.STATE_REFLECT: {"message", "thought"},
        ReflectionNodeKind.CONTINUITY_COMPRESS: {"segment_summary", "conversation_digest"},
        ReflectionNodeKind.PAGE_COMPOSE: {"segment_summary", "message", "thought", "author_chunk"},
        ReflectionNodeKind.GRAPH_EXTRACT: {"segment_summary", "message", "thought", "author_chunk"},
        ReflectionNodeKind.CORE_MEMORY_VIEW: {"formal_fact"},
        ReflectionNodeKind.STATE_SUMMARY_VIEW: {"formal_fact"},
        ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW: {"formal_fact"},
        ReflectionNodeKind.VIEW_REFRESH_PLANNER: {"formal_fact"},
    }
    targets = source_actors(graph)
    relations = graph.self.model_copy(
        update={
            "relationships": tuple(
                item for item in graph.self.relationships if item.target in targets
            )
        }
    )
    return NodePromptProjection(
        render_identity(graph.self, include_voice=False),
        render_state(graph.self) if kind in state_nodes else "",
        render_relationships(relations) if kind in relationship_nodes else "",
        render_memory(graph.memory) if kind in memory_nodes else "",
        tuple(
            material
            for material in graph.materials
            if material.kind in material_kinds[kind]
            and (
                kind
                not in {
                    ReflectionNodeKind.CORE_MEMORY_VIEW,
                    ReflectionNodeKind.STATE_SUMMARY_VIEW,
                    ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
                }
                or material.fact_kind
                == {
                    ReflectionNodeKind.CORE_MEMORY_VIEW: "memory_entry",
                    ReflectionNodeKind.STATE_SUMMARY_VIEW: "character_state",
                    ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW: "relationship",
                }[kind]
            )
        ),
    )
