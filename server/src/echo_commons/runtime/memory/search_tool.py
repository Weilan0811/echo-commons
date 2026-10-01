from __future__ import annotations

from collections.abc import Mapping

from echo_commons.agents.harness.progress import ProgressKey
from echo_commons.agents.harness.tools import ToolContext, ToolResult
from echo_commons.services.memory import MemorySearchScope, MemorySearchService
from echo_commons.services.memory.retrieval import MemorySourceChangedError

_MAX_QUERY_CHARS = 256
_MAX_RESULTS = 5


class MemorySearchTool:
    name = "memory_search"
    description = "在角色可见的长期记忆和相关对话中检索有限的记忆线索。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "想回想的主题、人物或事件",
                "minLength": 1,
                "maxLength": _MAX_QUERY_CHARS,
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_RESULTS,
                "default": _MAX_RESULTS,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, search: MemorySearchService, *, account_id: str) -> None:
        account = account_id.strip()
        if not account:
            raise ValueError("account_id must be non-empty")
        self.search = search
        self.account_id = account

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        policy = context.snapshot.memory_context.access_policy
        if not policy.search_enabled or policy.search_tool_name != self.name:
            return ToolResult(
                call_id=context.call_id,
                name=self.name,
                ok=False,
                error_code="memory_search_not_authorized",
            )
        query, limit, error_code = _parse_arguments(arguments)
        if error_code is not None:
            return ToolResult(
                call_id=context.call_id,
                name=self.name,
                ok=False,
                error_code=error_code,
            )
        scope = MemorySearchScope(
            account_id=self.account_id,
            character_id=context.snapshot.character_id,
        )
        try:
            hits = await self.search.search(
                scope,
                query,
                limit=limit,
                now_utc=context.snapshot.now_utc,
                expected_source_version=policy.expected_source_version,
                frozen_conversation_id=policy.frozen_conversation_id,
                frozen_max_sequence=policy.frozen_max_sequence,
            )
        except MemorySourceChangedError:
            return ToolResult(
                call_id=context.call_id,
                name=self.name,
                ok=False,
                error_code="memory_source_changed",
            )
        except Exception:
            return ToolResult(
                call_id=context.call_id,
                name=self.name,
                ok=False,
                error_code="memory_search_failed",
            )
        return ToolResult(
            call_id=context.call_id,
            name=self.name,
            ok=True,
            output={
                "retrievalKind": hits[0].retrieval_kind if hits else "fts5",
                "results": tuple(_public_hit(hit) for hit in hits),
            },
        )


def _parse_arguments(arguments: Mapping[str, object]) -> tuple[str, int, str | None]:
    raw_query = arguments.get("query")
    if not isinstance(raw_query, str):
        return "", _MAX_RESULTS, "invalid_query"
    query = raw_query.strip()
    if not query:
        return "", _MAX_RESULTS, "invalid_query"
    if len(query) > _MAX_QUERY_CHARS:
        return "", _MAX_RESULTS, "query_too_long"
    raw_limit = arguments.get("limit", _MAX_RESULTS)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        return query, _MAX_RESULTS, "invalid_limit"
    if not 1 <= raw_limit <= _MAX_RESULTS:
        return query, _MAX_RESULTS, "invalid_limit"
    return query, raw_limit, None


def _public_hit(hit: object) -> dict[str, object]:
    from echo_commons.services.memory.retrieval import MemorySearchHit

    if not isinstance(hit, MemorySearchHit):
        return {}
    payload: dict[str, object] = {
        "sourceKind": hit.source_kind,
        "contentVersion": hit.content_version,
        "retrievalPolicyVersion": hit.retrieval_policy_version,
        "sourceId": hit.source_id,
        "sourceRef": hit.source_ref,
        "summary": hit.summary,
    }
    if hit.memory_id is not None:
        payload["memoryId"] = hit.memory_id
    if hit.memory_kind is not None:
        payload["memoryKind"] = hit.memory_kind
    if hit.occurred_at_utc is not None:
        payload["occurredAtUtc"] = hit.occurred_at_utc.isoformat()
    return payload


def memory_search_progress_keys(result: ToolResult) -> tuple[ProgressKey, ...]:
    if not result.ok:
        return ()
    raw_results = result.output.get("results", ())
    return tuple(
        (item["sourceId"], item["contentVersion"])
        for item in raw_results
        if isinstance(item, Mapping)
        and isinstance(item.get("sourceId"), str)
        and isinstance(item.get("contentVersion"), str)
    )


__all__ = ["MemorySearchTool", "memory_search_progress_keys"]
