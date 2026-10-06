from echo_commons.modules.characters.domain.instance import CharacterInstance, MemoryMode
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.errors import ConflictError


def require_graph(
    instance: CharacterInstance, kind: ReflectionGraphKind, source_kind: str | None = None
) -> None:
    initializing = (
        instance.memory_status == "preparing"
        and instance.memory_mode is MemoryMode.FULL
        and (
            (kind is ReflectionGraphKind.MEMORY_ORGANIZE and source_kind == "author_material_batch")
            or (kind is ReflectionGraphKind.VIEW_REFRESH and source_kind == "memory_change_set")
        )
    )
    if not initializing:
        instance.require_ready()
    if kind is ReflectionGraphKind.DIARY_COMPOSE:
        raise ConflictError("Diary execution is outside the active memory workflow")
    if instance.memory_mode is MemoryMode.SIMPLE and kind not in {
        ReflectionGraphKind.SEGMENT_REFLECT,
        ReflectionGraphKind.CONTINUITY_COMPRESS,
    }:
        raise ConflictError("Simple memory mode does not run long-term reflection")


def allows_follow_up(instance: CharacterInstance) -> bool:
    return instance.memory_mode is MemoryMode.FULL
