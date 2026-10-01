import asyncio
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from echo_commons.agents.harness.progress import ProgressKey
from echo_commons.agents.harness.tools import ToolContext, ToolResult
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.shared.errors import ConflictError


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: StrictStr = Field(min_length=1, max_length=1000)
    limit: StrictInt = Field(default=5, ge=1, le=5)


class MemorySearchTool:
    name = "memory_search"

    def __init__(self, database: Database, retrieval: MemoryRetrieval) -> None:
        self.database, self.retrieval = database, retrieval

    @property
    def definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "检索当前角色有权查看的过去消息与自身记忆。",
                "parameters": SearchArguments.model_json_schema(),
            },
        }

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        try:
            parsed = SearchArguments.model_validate(arguments)
        except ValidationError as error:
            field = error.errors()[0]["loc"][0] if error.errors()[0]["loc"] else "query"
            code = "invalid_limit" if field == "limit" else "invalid_query"
            return self._error(context, code)
        if not parsed.query.strip():
            return self._error(context, "invalid_query")
        return await asyncio.to_thread(self._search, parsed, context)

    def _search(self, arguments: SearchArguments, context: ToolContext) -> ToolResult:
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
        )
        try:
            with self.database.read() as connection:
                hits = self.retrieval.search(
                    connection,
                    scope,
                    arguments.query,
                    limit=arguments.limit,
                    expected_source_version=version,
                )
        except ConflictError:
            return self._error(context, "memory_source_changed")
        except sqlite3.Error:
            return self._error(context, "memory_search_failed")
        return ToolResult(
            call_id=context.call_id,
            name=self.name,
            ok=True,
            output={
                "items": [
                    {
                        "source_kind": hit.source_kind,
                        "source_id": hit.source_id,
                        "source_version": hit.source_version,
                        "text": hit.text,
                        "conversation_id": hit.conversation_id,
                    }
                    for hit in hits
                ]
            },
        )

    def _error(self, context: ToolContext, code: str) -> ToolResult:
        return ToolResult(call_id=context.call_id, name=self.name, ok=False, error_code=code)


def memory_progress(result: ToolResult) -> tuple[ProgressKey, ...]:
    return tuple(
        (item["source_kind"], item["source_id"], item["source_version"])
        for item in result.output["items"]
    )
