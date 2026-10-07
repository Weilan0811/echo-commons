import json
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files
from uuid import UUID, uuid4

from pydantic import ValidationError

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.agents.harness.prompt import render_persona, render_prompt_section
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.models.protocol import (
    ModelGatewayError,
    ModelRequest,
    ModelResponseKind,
    PromptMessage,
)
from echo_commons.modules.characters.domain.authoring import (
    OUTPUT_ADAPTER,
    AuthoringContent,
    BasicOutput,
    CalibrateOutput,
    CandidateOutput,
    CandidateRequest,
    InterviewOutput,
    StoryOutput,
    merge_candidate,
)

AUTHORING_CONTRACT = OutputContractRef(kind="character_authoring", version="1.0")


@dataclass
class AuthoringUsage:
    model_requests: int = 0
    provider_requests: int = 0
    usage: UsageSummary = field(default_factory=UsageSummary)

    def summary(self) -> dict:
        return self.usage.model_dump() | {"provider_request_count": self.provider_requests}


class AuthoringFailure(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        self.code, self.status_code = code, status_code
        super().__init__(code)


def validate_candidate(
    output: dict,
    content: AuthoringContent,
    request: CandidateRequest,
) -> CandidateOutput:
    candidate = OUTPUT_ADAPTER.validate_python(output)
    if candidate.operation != request.operation:
        raise ValueError("Output operation must match request")
    merge_candidate(content, candidate)
    if candidate.operation == "interview" and {
        item.question_id for item in candidate.answers
    } != set(request.question_ids):
        raise ValueError("Answer exactly the selected questions")
    if candidate.operation == "calibrate":
        allowed = {"description", "profile", "voice", "relational_dynamics"}
        if content.story.strip():
            allowed.add("story")
        allowed.update("interview:" + item.question_id for item in content.interview)
        for item in (*candidate.changes, *candidate.conflicts):
            if not set(item.source_refs) <= allowed:
                raise ValueError("Calibration references must belong to frozen input")
    return candidate


class AuthoringAgent:
    def __init__(self, budget: ModelBudget) -> None:
        self.budget = budget
        self.prompts = {
            operation: files("echo_commons")
            .joinpath(f"resources/authoring/{operation}.md")
            .read_text(encoding="utf-8")
            for operation in ("basic", "story", "interview", "calibrate")
        }

    async def generate(
        self,
        content: AuthoringContent,
        request: CandidateRequest,
        questions: list[dict],
        *,
        player_id: str,
        profile: str,
        deadline: datetime,
        usage: AuthoringUsage,
        frozen_input: dict,
    ) -> CandidateOutput:
        prompt = self.prompts[request.operation]
        if request.operation == "interview":
            basis = frozen_input["interview_basis"]
            persona = render_persona(
                basis["agent_contract"],
                basis["profile"],
                basis["relational_dynamics"],
                basis["voice"],
            )
            prompt = (
                "\n\n".join(render_prompt_section(name, body) for name, body in persona)
                + "\n\n"
                + basis["expression_guidance"]
                + "\n\n"
                + prompt
            )
        schema = {
            "basic": BasicOutput,
            "story": StoryOutput,
            "interview": InterviewOutput,
            "calibrate": CalibrateOutput,
        }[request.operation].model_json_schema()
        prompt += "\n只返回符合以下结构的一个 JSON 对象：\n" + json.dumps(
            schema, ensure_ascii=False
        )
        payload = {"request": frozen_input["request"], "content": frozen_input["content"]}
        if request.operation == "interview":
            payload = {
                "request": frozen_input["request"],
                "author_story": basis["story"],
                "selected_questions": questions,
                "existing_answers": [item.model_dump() for item in content.interview],
            }
        messages = [
            PromptMessage(role="system", content=prompt),
            PromptMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        trace_id = uuid4()

        async def before_request() -> None:
            usage.provider_requests += 1

        for index in range(1, 3):
            usage.model_requests += 1
            model_request = ModelRequest(
                invocation_id=UUID(str(request.candidate_id)),
                trace_id=trace_id,
                agent_id=f"author:{player_id}",
                model_profile=profile,
                attempt=1,
                step_index=index,
                messages=tuple(messages),
                output_contract=AUTHORING_CONTRACT,
                max_output_tokens=6000,
                deadline_utc=deadline,
            )
            try:
                response = await self.budget.generate(model_request, before_request=before_request)
            except ModelGatewayError as error:
                raise AuthoringFailure("authoring_model_unavailable", 503) from error
            usage.usage = usage.usage.add(response.usage_summary)
            try:
                if response.kind != ModelResponseKind.TERMINAL:
                    raise ValueError("Authoring requires a terminal JSON object")
                candidate = validate_candidate(response.output, content, request)
                return candidate
            except (ValidationError, ValueError) as error:
                messages.append(
                    PromptMessage(
                        role="assistant",
                        content=json.dumps(response.output, ensure_ascii=False),
                    )
                )
                messages.append(
                    PromptMessage(
                        role="user",
                        content="修正输出字段与约束，保留原始输入。错误：" + str(error),
                    )
                )
        raise AuthoringFailure("authoring_output_invalid", 502)
