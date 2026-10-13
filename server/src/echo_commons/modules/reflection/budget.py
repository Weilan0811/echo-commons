from dataclasses import dataclass

from echo_commons.modules.reflection.contracts.candidates import (
    MemoryFactCandidate,
    MemoryFactReviewAction,
    ReflectionBatchProposal,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial


@dataclass(frozen=True, slots=True)
class ReflectionBudget:
    max_candidates: int = 64
    max_output_chars: int = 20000
    initialization_max_candidates: int = 256
    initialization_max_output_chars: int = 160000
    initialization_chars_per_input_char: int = 6
    initialization_candidates_per_material: int = 8
    core_memory_max_chars: int = 600
    relationship_attitude_max_chars: int = 300

    def for_node(self, context):
        count, chars = self.limits(context.graph_snapshot)
        if context.node_key == "cognition_reflect":
            approved = next(
                item.payload
                for item in context.artifacts
                if isinstance(item.payload, MemoryFactReviewAction)
            )
            candidates = tuple(
                MemoryFactCandidate(source_refs=item.evidence_refs, operation=item)
                for item in approved.facts
            )
            used = ReflectionBatchProposal(candidates=candidates) if candidates else None
            count -= approved.used_candidates if approved.saved_facts else len(candidates)
            chars -= (
                approved.used_content_chars
                if approved.saved_facts
                else used.content_chars
                if used
                else 0
            )
        return count, chars

    def limits(self, snapshot: GraphContextSnapshot) -> tuple[int, int]:
        if snapshot.source_kind != "author_material_batch":
            return self.max_candidates, self.max_output_chars
        chars = sum(
            len(item.message.text) if isinstance(item, MessageMaterial) else len(item.content)
            for item in snapshot.materials
        )
        return (
            min(
                self.initialization_max_candidates,
                max(
                    self.max_candidates,
                    len(snapshot.materials) * self.initialization_candidates_per_material,
                ),
            ),
            min(
                self.initialization_max_output_chars,
                max(
                    self.max_output_chars,
                    chars * self.initialization_chars_per_input_char + 8000,
                ),
            ),
        )
