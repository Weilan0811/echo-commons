from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

STRONG_PROFILE = "strong"
LIGHT_PROFILE = "light"


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """The requested and effective logical profile for one task."""

    task_kind: str
    requested_profile: str
    resolved_profile: str
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TaskRouting:
    """Immutable logical task routing loaded from the model registry."""

    default_profile: str = LIGHT_PROFILE
    task_profiles: Mapping[str, str] = field(default_factory=dict)
    strong_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.default_profile.strip():
            raise ValueError("default model profile must be named")
        if not isinstance(self.strong_enabled, bool):
            raise ValueError("strong_enabled must be a boolean")
        for task_kind, profile in self.task_profiles.items():
            if not task_kind.strip() or not profile.strip():
                raise ValueError("task routes must map non-empty names")

    def route_for(self, task_kind: str) -> ModelRoute:
        """Resolve one task without consulting credentials or call failures."""

        normalized_task_kind = task_kind.strip()
        if not normalized_task_kind:
            raise ValueError("task kind must be named")
        requested_profile = self.task_profiles.get(normalized_task_kind, self.default_profile)
        if not self.strong_enabled and requested_profile == STRONG_PROFILE:
            return ModelRoute(
                task_kind=normalized_task_kind,
                requested_profile=requested_profile,
                resolved_profile=LIGHT_PROFILE,
                fallback_reason="strong_disabled",
            )
        return ModelRoute(
            task_kind=normalized_task_kind,
            requested_profile=requested_profile,
            resolved_profile=requested_profile,
        )
