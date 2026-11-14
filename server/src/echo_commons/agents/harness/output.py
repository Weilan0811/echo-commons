from pydantic import ValidationError

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.run import AgentOutput
from echo_commons.infrastructure.models.protocol import ModelResponse, ModelResponseKind


class ModelOutputError(ValueError):
    code = "invalid_model_output"

    def __init__(self, message: str, *, repair_hint: str | None = None):
        super().__init__(message)
        self.repair_hint = repair_hint


class OutputContentTooLong(ModelOutputError):
    code = "output_content_too_long"


def check_content_length(body: dict, limit: int | None) -> None:
    field = "summary" if "summary" in body else "content"
    content = body.get(field)
    if limit is not None and isinstance(content, str) and len(content) > limit:
        raise OutputContentTooLong(
            "Output content exceeds this invocation's character budget",
            repair_hint=f"{field} 正文实际 {len(content)} 个字符，上限 {limit} 个字符。"
            "请缩短正文，保留重要结果、人物与必要条件，返回符合原契约的完整 JSON。",
        )


def parse_terminal_output(
    response: ModelResponse,
    invocation: AgentInvocation,
    outputs: OutputRegistry,
    *,
    evidence_refs: tuple[str, ...] | None = None,
) -> AgentOutput:
    if response.kind is not ModelResponseKind.TERMINAL or response.output is None:
        raise ModelOutputError("Model response requires terminal output")
    try:
        payload = outputs.parse(
            invocation.output_contract, response.output, evidence_refs=evidence_refs
        )
    except ValidationError as error:
        fields = "; ".join(
            ".".join(str(part) for part in item["loc"]) + ": " + item["msg"]
            for item in error.errors(include_input=False, include_url=False)[:3]
        )
        raise ModelOutputError(
            "Output does not match its registered contract",
            repair_hint="请修正以下字段，并返回符合原契约的完整 JSON：" + fields[:400],
        ) from error
    limit = invocation.execution_policy.max_content_chars
    check_content_length(payload.model_dump(), limit)
    return AgentOutput(contract=invocation.output_contract, payload=payload)
