import json

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from echo_commons.agents.contracts.output import compact_schema
from echo_commons.agents.harness.progress import ProgressKey
from echo_commons.agents.harness.tools import ToolContext, ToolResult
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.modules.memory.domain.presentation import compact_memory_text
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.shared.errors import ConflictError


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: StrictStr = Field(min_length=1, max_length=256, description="想回想的主题、人物或事件")
    limit: StrictInt = Field(ge=1)


class MemorySearchTool:
    name = "memory_search"

    def __init__(self, database: Database, retrieval: MemoryRetrieval, *, max_results: int) -> None:
        if not 1 <= max_results <= 5:
            raise ValueError("Memory search result limit must be between 1 and 5")
        self.database, self.retrieval = database, retrieval
        self.max_results = max_results

    @property
    def definition(self) -> dict[str, object]:
        parameters = SearchArguments.model_json_schema()
        parameters["properties"]["limit"].update(maximum=self.max_results, default=self.max_results)
        parameters["required"].remove("limit")
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "在角色可见的长期记忆和相关对话中检索有限的记忆线索。"
                "budgetLimited 表示容量限制，summaryTruncated 表示该项仅为原文摘录。",
                "parameters": compact_schema(parameters),
            },
        }

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        if isinstance(arguments.get("query"), str):
            arguments = {**arguments, "query": arguments["query"].strip()}
        try:
            parsed = SearchArguments.model_validate({"limit": self.max_results, **arguments})
        except ValidationError as error:
            field = error.errors()[0]["loc"][0] if error.errors()[0]["loc"] else "query"
            code = (
                "invalid_limit"
                if field == "limit"
                else (
                    "query_too_long"
                    if error.errors()[0]["type"] == "string_too_long"
                    else "invalid_query"
                )
            )
            return self._error(context, code)
        if parsed.limit > self.max_results:
            return self._error(context, "invalid_limit")
        if not parsed.query.strip():
            return self._error(context, "invalid_query")
        return await self._search(parsed, context)

    async def _search(self, arguments: SearchArguments, context: ToolContext) -> ToolResult:
        policy = context.read_policy
        version = next(
            (
                item.version
                for item in policy.source_versions
                if item.kind == "memory_search" and item.source_id == context.scope.character_id
            ),
            None,
        )
        if version is None:
            return self._error(context, "memory_search_not_authorized")
        scope = SearchScope(
            context.scope.community_id,
            context.scope.character_id,
            policy.observed_at_utc,
            policy.conversation_id,
            policy.upper_sequence,
            conversations=policy.conversations,
        )
        try:
            hits = await self.retrieval.search_async(
                self.database,
                scope,
                arguments.query,
                limit=arguments.limit,
                expected_source_version=version,
            )
        except ConflictError:
            return self._error(context, "memory_source_changed")
        except StorageError:
            return self._error(context, "memory_search_failed")
        output = {
            "retrievalKind": "hybrid" if self.retrieval.vectors else "fts5",
            "results": [],
        }
        for hit in hits:
            item = {
                "sourceKind": hit.source_kind,
                "sourceId": hit.source_id,
                "sourceRef": f"{hit.source_kind}:{hit.source_id}",
                "contentVersion": hit.source_version,
                "retrievalPolicyVersion": "fts5-v1",
                "summary": compact_memory_text(hit.text),
                "context": hit.context_label,
            }
            proposed = {**output, "results": [*output["results"], item]}
            limit = context.max_output_chars
            if limit is not None and len(json.dumps(proposed, ensure_ascii=False)) > limit:
                output["budgetLimited"] = True
                item["summaryTruncated"] = True
                while (
                    item["summary"] and len(json.dumps(proposed, ensure_ascii=False)) + 32 > limit
                ):
                    item["summary"] = item["summary"][: len(item["summary"]) // 2]
                if item["summary"]:
                    output["results"].append(item)
                break
            output["results"].append(item)
        return ToolResult(
            call_id=context.call_id,
            name=self.name,
            ok=True,
            output=output,
        )

    def _error(self, context: ToolContext, code: str) -> ToolResult:
        return ToolResult(call_id=context.call_id, name=self.name, ok=False, error_code=code)


def memory_progress(result: ToolResult) -> tuple[ProgressKey, ...]:
    return tuple(
        (item["sourceKind"], item["sourceId"], item["contentVersion"])
        for item in result.output["results"]
    )
