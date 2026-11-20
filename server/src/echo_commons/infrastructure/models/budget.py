import json
from functools import lru_cache
from math import ceil

import tiktoken
from pydantic import BaseModel, ConfigDict, Field, model_validator


@lru_cache(maxsize=8)
def encoding(name):
    return tiktoken.get_encoding(name)


def prepare_counters(registry):
    # 编码表在组装应用时加载，业务写事务只执行已经准备好的本地计量。
    for entry in registry.entries.values():
        if entry.enabled and entry.token_counter != "utf8_bytes":
            encoding(entry.token_counter)


class InputBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_entry_id: str
    model_configuration: dict[str, object] | None = None
    context_window_tokens: int = Field(ge=1)
    output_tokens: int = Field(ge=1)
    token_counter: str = "utf8_bytes"
    max_chars: int = Field(default=32000, ge=1)
    tool_definitions: tuple[dict[str, object], ...] = ()
    additional_limits: tuple["InputBudget", ...] = ()
    output_instructions: str = ""

    @model_validator(mode="after")
    def available_capacity(self):
        if self.context_window_tokens <= self.output_tokens:
            raise ValueError("Output reservation exhausts the model context window")
        return self

    def count(self, text: str) -> int:
        if self.token_counter == "utf8_bytes":
            return len(text.encode("utf-8"))
        return len(encoding(self.token_counter).encode(text, disallowed_special=()))

    def measure(self, messages, tool_definitions=()) -> int:
        # 内容与协议结构一起计量；未知模型使用明确配置的 UTF-8 字节上界。
        payload = json.dumps(
            {
                "messages": [
                    *({"role": m.role, "content": m.content} for m in messages),
                    *(
                        [{"role": "user", "content": self.output_instructions}]
                        if self.output_instructions
                        else []
                    ),
                ],
                "tools": tool_definitions or self.tool_definitions,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        available = self.context_window_tokens - self.output_tokens
        return max(
            len(payload),
            ceil(self.count(payload) * self.max_chars / available),
            *(
                ceil(
                    b.measure(messages, tool_definitions or self.tool_definitions)
                    * self.max_chars
                    / b.max_chars
                )
                for b in self.additional_limits
            ),
        )


def request_fits(entry, request) -> bool:
    if (request.max_output_tokens or entry.max_output_tokens) >= entry.context_window_tokens:
        return False
    budget = InputBudget(
        model_entry_id=entry.entry_id,
        context_window_tokens=entry.context_window_tokens,
        output_tokens=request.max_output_tokens or entry.max_output_tokens,
        token_counter=entry.token_counter,
        max_chars=2**31 - 1,
    )
    return budget.measure(request.messages, request.tool_definitions) <= budget.max_chars
