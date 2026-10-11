from dataclasses import dataclass

from echo_commons.agents.harness.prompt import (
    render_identity,
    render_memory,
    render_relationships,
    render_state,
)
from echo_commons.modules.memory.domain.views import ViewReadingScope
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.context import (
    ReflectionMaterial,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import (
    ReflectionNodeKind,
    reflection_graph_definition,
)


@dataclass(frozen=True, slots=True)
class NodePromptProjection:
    identity_sections: tuple[tuple[str, str], ...]
    state: str
    relationships: str
    memory: str
    materials: tuple[ReflectionMaterial, ...]
    reading_scope: ViewReadingScope | None

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(material.evidence_ref for material in self.materials)


def select_node_materials(node: ReflectionNodeInput) -> tuple[ReflectionMaterial, ...]:
    definition = reflection_graph_definition(node.graph_snapshot.graph_kind).node(node.node_key)
    return tuple(
        material
        for material in node.graph_snapshot.materials
        if material.kind in definition.material_kinds
        and (definition.fact_kind is None or material.fact_kind == definition.fact_kind)
    )


def project_node_input(node: ReflectionNodeInput) -> NodePromptProjection:
    graph = node.graph_snapshot
    definition = reflection_graph_definition(graph.graph_kind).node(node.node_key)
    identity = (
        (("character_identity", f"你叫{graph.self.name}。以角色第一人称整理已发生的经历。"),)
        if node.node_kind is ReflectionNodeKind.CONTINUITY_COMPRESS
        else render_identity(
            graph.self,
            include_voice=node.node_kind
            in {
                ReflectionNodeKind.CORE_MEMORY_VIEW,
                ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
            },
        )
    )
    targets = source_actors(graph)
    relations = graph.self.model_copy(
        update={
            "relationships": tuple(
                item for item in graph.self.relationships if item.target in targets
            )
        }
    )
    return NodePromptProjection(
        identity,
        render_state(graph.self) if "state" in definition.background_sections else "",
        render_relationships(relations)
        if "relationships" in definition.background_sections
        else "",
        render_memory(graph.memory) if "memory" in definition.background_sections else "",
        select_node_materials(node),
        ViewReadingScope.from_materials(item.model_dump(mode="json") for item in graph.materials)
        if definition.view_kind == "core_memory"
        else None,
    )
