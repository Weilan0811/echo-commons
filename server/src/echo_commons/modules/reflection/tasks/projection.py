import json
from collections import Counter
from dataclasses import dataclass

from echo_commons.agents.harness.prompt import (
    actor_label,
    render_memory,
    render_relationships,
)
from echo_commons.modules.memory.domain.organization import (
    CognitionAdd,
    CognitionReplace,
    FactAdd,
    FactCandidateRef,
    MemoryCognitionContent,
    MemoryFactContent,
    MemoryRecordRef,
    SavedFactRef,
)
from echo_commons.modules.memory.domain.views import ViewReadingScope
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestAction,
    ContinuityModelAction,
    FollowUpDecision,
    MemoryCognitionReflectAction,
    MemoryFactExtractAction,
    MemoryFactReviewAction,
    MemoryModelAction,
    NoOpModelAction,
    NoOpReflectionAction,
    RelationshipDimensionAction,
    RelationshipModelAction,
    RelationshipReflectionAction,
    RelationshipTargetDecision,
    SegmentSummaryAction,
    SegmentSummaryModelAction,
    StateModelAction,
    StateReflectionAction,
    ViewModelAction,
    ViewRefreshAction,
)
from echo_commons.modules.reflection.contracts.context import (
    ReflectionMaterial,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import (
    ReflectionNodeKind,
    reflection_graph_definition,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import SystemSource


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
    materials = tuple(
        material
        for material in node.graph_snapshot.materials
        if material.kind in definition.material_kinds
        and (definition.fact_kind is None or material.fact_kind == definition.fact_kind)
        and (
            node.node_kind not in (ReflectionNodeKind.FACT_EXTRACT, ReflectionNodeKind.FACT_REVIEW)
            or material.kind != "formal_fact"
            or material.fact_kind == "memory_fact"
        )
        and (
            definition.view_kind != "core_memory"
            or material.fact_kind in ("memory_fact", "memory_cognition")
        )
    )
    if node.node_kind is not ReflectionNodeKind.FACT_EXTRACT:
        return materials
    return tuple(
        sorted(
            materials,
            key=lambda material: (
                (0, material.message.occurred_at_utc, material.source_id)
                if material.kind == "message"
                else (1, material.source_id)
            ),
        )
    )


def project_node_input(node: ReflectionNodeInput) -> NodePromptProjection:
    graph = node.graph_snapshot
    definition = reflection_graph_definition(graph.graph_kind).node(node.node_key)
    own = ActorRef("character", graph.scope.character_id)
    owner = actor_label(own, graph.self.name, own)
    identity = (
        (("character_identity", f"你是{owner}。以角色第一人称整理已发生的经历。"),)
        if node.node_kind is ReflectionNodeKind.CONTINUITY_COMPRESS
        else (
            (
                "character_identity",
                f"整理{owner}的经历与认识，遵守当前整理节点的任务规则。",
            ),
            ("character_profile", graph.self.profile),
            ("character_relational_dynamics", graph.self.relational_dynamics),
        )
    )
    if node.node_kind in {
        ReflectionNodeKind.CORE_MEMORY_VIEW,
        ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
        ReflectionNodeKind.COGNITION_REFLECT,
    }:
        identity = (*identity, ("character_voice", graph.self.voice))
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
        "当前状态背景：\n"
        + "\n".join(
            f"{name}：{value}"
            for name, value in (
                ("可用状态", graph.self.availability),
                ("身体状况", graph.self.physical_state),
                ("心情", graph.self.mood),
                ("正在做的事情", graph.self.activity),
            )
            if value
        )
        if "state" in definition.background_sections
        else "",
        render_relationships(relations)
        if "relationships" in definition.background_sections
        else "",
        render_memory(graph.memory) if "memory" in definition.background_sections else "",
        select_node_materials(node),
        ViewReadingScope.from_materials(item.model_dump(mode="json") for item in graph.materials)
        if definition.view_kind == "core_memory"
        else None,
    )


@dataclass(frozen=True, slots=True)
class NodeReferences:
    node: ReflectionNodeInput
    sources: dict[int, str]
    originals: dict[int, ReflectionMaterial]
    records: dict[int, MemoryRecordRef]
    bodies: dict[int, dict]
    candidates: dict[int, tuple[str, MemoryFactContent]]

    @classmethod
    def from_input(cls, node):
        sources, originals, records, bodies, candidates = {}, {}, {}, {}, {}
        for number, material in enumerate(select_node_materials(node), 1):
            sources[number] = material.evidence_ref
            originals[number] = material
            if material.kind == "formal_fact" and material.fact_kind in (
                "memory_fact",
                "memory_cognition",
            ):
                records[number] = MemoryRecordRef(
                    record_kind=material.fact_kind.removeprefix("memory_"),
                    memory_id=material.source_id,
                    version=int(material.version),
                )
                bodies[number] = json.loads(material.content)
        for artifact in node.artifacts:
            if not isinstance(artifact.payload, MemoryFactReviewAction):
                continue
            for fact in artifact.payload.facts:
                if fact.operation == "support":
                    body = bodies[next(n for n, ref in records.items() if ref == fact.previous)]
                    content = MemoryFactContent(
                        topic=body["topic"],
                        content=body["content"],
                        participants=json.loads(body["participants_json"]),
                        occurred_at_utc=body["occurred_at_utc"],
                        conditions=body["conditions"],
                        salience=body["salience"],
                    )
                else:
                    content = fact.fact
                number = len(sources) + len(candidates) + 1
                candidates[number] = fact.local_key, content
            for fact in artifact.payload.saved_facts:
                if fact.reference not in records.values():
                    number = max((*sources, *records, *candidates), default=0) + 1
                    records[number] = fact.reference
                    bodies[number] = fact.fact.model_dump(mode="json")
        return cls(node, sources, originals, records, bodies, candidates)

    def source_label(self, ref):
        return next(number for number, value in self.sources.items() if value == ref)

    def actor_names(self):
        graph = self.node.graph_snapshot
        names = {item.target: item.target_name for item in graph.self.relationships}
        for session in graph.activity_sessions:
            names.update((p.actor, p.display_name) for p in session.participants)
        for material in graph.materials:
            if material.kind == "message" and isinstance(material.message.sender, ActorRef):
                names[material.message.sender] = material.message.sender_name
            elif material.kind == "game_event":
                content = json.loads(material.content)
                for reference, name in content.get("participants", {}).items():
                    kind, identity = reference.split(":", 1)
                    names[ActorRef(kind, identity)] = name
        names[ActorRef("character", graph.scope.character_id)] = graph.self.name
        return names

    def display_record(self, value):
        # 模型只读取材料含义，正式身份和版本保留在冻结输入中。
        keys = (
            "topic",
            "content",
            "conditions",
            "occurred_at_utc",
            "formed_at_utc",
            "applies_to",
            "status",
            "observer_name",
            "target_name",
            "relationship_type",
            "previous_attitude",
            "initial_description",
            "evidence",
            "evidence_kind",
            "source_kind",
            "content_status",
            "target_messages",
            "long_term_records",
            "supporting_materials",
            "support_readable",
        )
        if isinstance(value, dict):
            return {key: self.display_record(item) for key, item in value.items() if key in keys}
        if isinstance(value, list):
            return [self.display_record(item) for item in value]
        return value

    def predecessor_text(self):
        lines = [
            f"[材料{number}] 本批事实记录（保存操作已确定）\n{content.content}"
            for number, (_, content) in self.candidates.items()
        ]
        lines.extend(
            f"[材料{number}] 已保存事实\n{self.bodies[number]['content']}"
            for number in self.records
            if number not in self.originals
        )
        return "\n\n".join(lines)

    def raw_refs(self, numbers, kinds):
        return tuple(
            dict.fromkeys(
                self.sources[number]
                for number in numbers
                if number in self.originals and self.originals[number].kind in kinds
            )
        )

    def participants(self, numbers):
        actors = set()
        for number in numbers:
            if number in self.candidates:
                actors.update(self.candidates[number][1].participants)
            elif number in self.records and self.records[number].record_kind == "fact":
                body = self.bodies[number]
                values = (
                    json.loads(body["participants_json"])
                    if "participants_json" in body
                    else body.get("participants", [])
                )
                actors.update(ActorRef(value["kind"], value["actor_id"]) for value in values)
            elif number in self.originals:
                material = self.originals[number]
                if material.kind == "message":
                    if isinstance(material.message.sender, ActorRef):
                        actors.add(material.message.sender)
                    actors.update(material.mentions)
                elif material.kind == "game_event":
                    actors.update(material.actors)
                elif material.kind == "author_chunk":
                    actors.add(ActorRef("character", self.node.scope.character_id))
        return tuple(sorted(actors, key=lambda actor: (actor.kind.value, actor.actor_id)))

    def fact(self, item, index):
        refs = self.raw_refs(item.sources, {"message", "game_event", "author_chunk"})
        if not refs:
            if all(
                n in self.records and self.records[n].record_kind == "fact" for n in item.sources
            ):
                return None
            raise ValueError("Fact requires its original evidence")
        messages = [
            self.originals[n].message
            for n in item.sources
            if n in self.originals and self.originals[n].kind == "message"
        ]
        occurred = (
            min(message.occurred_at_utc for message in messages)
            if messages and all(isinstance(message.sender, SystemSource) for message in messages)
            else None
        )
        events = [
            self.originals[n]
            for n in item.sources
            if n in self.originals and self.originals[n].kind == "game_event"
        ]
        if events:
            occurred = min(e.occurred_at_utc for e in events)
        content = MemoryFactContent(
            topic=item.content[:80],
            content=item.content,
            participants=self.participants(item.sources),
            occurred_at_utc=occurred,
        )
        return FactAdd(local_key=f"fact{index}", fact=content, evidence_refs=refs)

    def cognition(self, item):
        refs = self.raw_refs(item.sources, {"thought", "author_chunk"})
        supports, previous = [], []
        for number in dict.fromkeys(item.sources):
            if number in self.candidates:
                supports.append(FactCandidateRef(local_key=self.candidates[number][0]))
            elif number in self.records:
                reference = self.records[number]
                if reference.record_kind == "fact":
                    supports.append(SavedFactRef(**reference.model_dump()))
                else:
                    previous.append(number)
        if not refs and not supports:
            if previous:
                return None
            raise ValueError("Cognition requires original or fact support")
        if (
            previous
            and self.bodies[previous[0]]["status"] == "current"
            and self.bodies[previous[0]]["content"].strip() == item.content.strip()
        ):
            return None
        targets = [
            actor
            for actor in self.participants(item.sources)
            if actor != ActorRef("character", self.node.scope.character_id)
        ]
        content = MemoryCognitionContent(
            topic=item.content[:80],
            content=item.content,
            applies_to=item.content[:200],
            target=targets[0] if len(targets) == 1 else None,
        )
        values = dict(
            cognition=content, supporting_facts=tuple(dict.fromkeys(supports)), evidence_refs=refs
        )
        if len(previous) == 1:
            return CognitionReplace(previous=self.records[previous[0]], **values)
        return CognitionAdd(**values)

    def bind(self, action):
        if isinstance(action, NoOpModelAction):
            return NoOpReflectionAction(kind="no_op", reason=action.reason)
        allowed = set(self.sources) | set(self.records) | set(self.candidates)
        if isinstance(
            action,
            (
                SegmentSummaryModelAction,
                RelationshipModelAction,
                StateModelAction,
                ContinuityModelAction,
            ),
        ):
            targets = self.targets()

            def references(numbers):
                if not numbers or len(numbers) != len(set(numbers)):
                    raise ValueError("Evidence numbers must be nonempty and unique")
                if any(
                    number not in self.originals or self.originals[number].context_only
                    for number in numbers
                ):
                    raise ValueError("Only new materials may support a change")
                return tuple(self.sources[number] for number in numbers)

            new_refs = tuple(
                material.evidence_ref
                for material in self.originals.values()
                if not material.context_only
            )
            if isinstance(action, SegmentSummaryModelAction):
                selected = tuple(
                    RelationshipTargetDecision(
                        target=targets[item.target], evidence_refs=references(item.sources)
                    )
                    for item in action.follow_up.relationship_targets
                )
                return SegmentSummaryAction(
                    kind="segment_summary",
                    summary=action.summary,
                    evidence_refs=new_refs,
                    follow_up=FollowUpDecision(
                        relationship_reflect=action.follow_up.relationship_reflect,
                        state_reflect=action.follow_up.state_reflect,
                        relationship_targets=selected,
                    ),
                )
            if isinstance(action, RelationshipModelAction):
                dimensions = tuple(
                    RelationshipDimensionAction(
                        target=targets[item.target],
                        evidence_refs=references(item.sources),
                        dimension=item.dimension,
                        direction=item.direction,
                        level=item.level,
                        evidence_kind=item.evidence_kind,
                    )
                    for item in action.dimensions
                )
                return RelationshipReflectionAction(
                    kind="relationship_reflection",
                    dimensions=dimensions,
                    evidence_refs=tuple(
                        dict.fromkeys(ref for item in dimensions for ref in item.evidence_refs)
                    ),
                )
            if isinstance(action, StateModelAction):
                return StateReflectionAction(
                    kind="state_reflection",
                    state_kind=action.state_kind,
                    value=action.value,
                    evidence_refs=references(action.sources),
                )
            return ContinuityDigestAction(
                kind="continuity_digest", content=action.content, evidence_refs=new_refs
            )
        if isinstance(action, MemoryModelAction):
            if any(set(item.sources) - allowed for item in action.items):
                raise ValueError("Unknown material number")
            if self.node.node_kind is ReflectionNodeKind.FACT_EXTRACT:
                facts = []
                for item in action.items:
                    fact = self.fact(item, len(facts) + 1)
                    if fact is None:
                        continue
                    facts.append(fact)
                if facts:
                    return MemoryFactExtractAction(
                        facts=tuple(facts),
                        evidence_refs=tuple(
                            dict.fromkeys(ref for fact in facts for ref in fact.evidence_refs)
                        ),
                    )
            else:
                cognitions = tuple(
                    value for item in action.items if (value := self.cognition(item)) is not None
                )
                updates = Counter(
                    (value.previous.memory_id, value.previous.version)
                    for value in cognitions
                    if isinstance(value, CognitionReplace)
                )
                cognitions = tuple(
                    CognitionAdd(**value.model_dump(exclude={"operation", "previous"}))
                    if isinstance(value, CognitionReplace)
                    and updates[value.previous.memory_id, value.previous.version] > 1
                    else value
                    for value in cognitions
                )
                if cognitions:
                    return MemoryCognitionReflectAction(
                        cognitions=cognitions,
                        evidence_refs=tuple(
                            dict.fromkeys(ref for item in cognitions for ref in item.evidence_refs)
                        ),
                    )
            return NoOpReflectionAction(kind="no_op", reason="本批没有需要保存的新记忆项。")
        if isinstance(action, ViewModelAction):
            if set(action.sources) - set(self.sources):
                raise ValueError("Unknown view material number")
            if not action.content.strip():
                return NoOpReflectionAction(kind="no_op", reason="本批没有需要改写的内容。")
            kind = (
                reflection_graph_definition(self.node.graph_snapshot.graph_kind)
                .node(self.node.node_key)
                .view_kind
            )
            target = None
            if kind == "relationship_attitude":
                material = next(
                    value for value in self.originals.values() if value.fact_kind == "relationship"
                )
                body = json.loads(material.content)
                target = ActorRef(body["target_kind"], body["target_id"])
            return ViewRefreshAction(
                kind="view_refresh",
                view_kind=kind,
                content=action.content,
                target=target,
                supporting_records=tuple(
                    self.records[n] for n in dict.fromkeys(action.sources) if n in self.records
                ),
                evidence_refs=tuple(self.sources[n] for n in dict.fromkeys(action.sources)),
            )
        return action

    def targets(self):
        return {
            number: actor
            for number, actor in enumerate(
                sorted(
                    source_actors(self.node.graph_snapshot),
                    key=lambda item: (item.kind.value, item.actor_id),
                ),
                1,
            )
        }
