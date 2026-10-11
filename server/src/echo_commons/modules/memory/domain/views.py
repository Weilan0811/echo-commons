import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class MemoryViewDraft:
    kind: str
    content: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ViewBranchResult:
    view_kind: Literal["core_memory", "state_summary", "relationship_attitude"]
    outcome: Literal["completed", "no_op"]


@dataclass(frozen=True, slots=True)
class ViewReadingScope:
    selected_memory_ids: list[str]
    unread_memory_ids: list[str]
    processed_versions: dict[str, str]
    eligible_versions: dict[str, str]
    complete: bool
    sources_readable: bool
    previous_core: str

    @classmethod
    def from_materials(cls, materials):
        for material in materials:
            if material["fact_kind"] == "core_memory_request":
                return cls(**json.loads(material["content"]))
        return None

    def prompt_data(self):
        return {
            "provided_page_count": len(self.selected_memory_ids),
            "unread_page_count": len(self.unread_memory_ids),
            "complete": self.complete,
            "sources_readable": self.sources_readable,
            "previous_content": self.previous_core,
        }
