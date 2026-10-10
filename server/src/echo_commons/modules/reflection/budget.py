from dataclasses import dataclass

from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial


@dataclass(frozen=True, slots=True)
class ReflectionBudget:
    max_candidates: int = 64
    max_output_chars: int = 20000
    initialization_max_candidates: int = 256
    initialization_max_output_chars: int = 160000
    initialization_chars_per_input_char: int = 6
    initialization_candidates_per_material: int = 8

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

    def node_limits(self, snapshot: GraphContextSnapshot, node_key: str) -> tuple[int, int]:
        count, chars = self.limits(snapshot)
        if snapshot.graph_kind == "memory_organize":
            # 两个并行节点分享写入额度，避免全部生成后才发现数量超限。
            pages = max(1, count // 3)
            return (pages if node_key == "page_compose" else count - pages, chars // 2)
        return count, chars
