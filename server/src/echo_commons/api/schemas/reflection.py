from __future__ import annotations

from pydantic import Field

from echo_commons.api.schemas.messages import ApiModel


class ReflectionRunViewResponse(ApiModel):
    graph_run: dict[str, object] = Field(alias="graphRun")
    node_tasks: list[dict[str, object]] = Field(alias="nodeTasks")
    artifacts: list[dict[str, object]]
    result: dict[str, object] | None
    facts: list[dict[str, object]]
    traces: list[dict[str, object]]


__all__ = ["ReflectionRunViewResponse"]
