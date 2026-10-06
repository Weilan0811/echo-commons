from echo_commons.modules.characters.domain.instance import CharacterInstance, MemoryMode
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.errors import ConflictError


def require_graph(instance: CharacterInstance, kind: ReflectionGraphKind) -> None:
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
