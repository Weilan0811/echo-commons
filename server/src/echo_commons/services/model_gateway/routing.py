"""Logical Agent backend and task-to-model routing.

This module deliberately contains no provider calls and no Runtime state.  It
only turns user-editable logical routing configuration into a deterministic
decision that Runtime can put on an immutable AgentInvocation.
"""

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


def resolve_agent_route(agent: object, task_kind: str) -> ModelRoute:
    """Resolve a route from a configured Agent, preserving legacy fixtures.

    Runtime tests and integrations may provide a minimal ``RunnableAgent``
    implementation that predates task routing.  Such an Agent keeps its
    existing ``model_profile`` instead of being silently changed to the
    application default.
    """

    route_for = getattr(agent, "route_for", None)
    if callable(route_for):
        route = route_for(task_kind)
        if not isinstance(route, ModelRoute):
            raise TypeError("Agent route_for() must return ModelRoute")
        return route

    profile = getattr(agent, "model_profile", LIGHT_PROFILE)
    if not isinstance(profile, str) or not profile.strip():
        profile = LIGHT_PROFILE
    return ModelRoute(
        task_kind=task_kind,
        requested_profile=profile,
        resolved_profile=profile,
    )


__all__ = [
    "LIGHT_PROFILE",
    "ModelRoute",
    "STRONG_PROFILE",
    "TaskRouting",
    "resolve_agent_route",
]
