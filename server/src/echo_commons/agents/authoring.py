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


def interview_review_messages(frozen: dict, output: dict | None, error: str | None):
    return [
        PromptMessage(role="system", content=frozen["interview_review_prompt"]),
        PromptMessage(
            role="user",
            content=json.dumps(
                {
                    "request": frozen["request"],
                    "character_materials": frozen["content"],
                    "author_story": frozen["interview_basis"]["story"],
                    "selected_questions": frozen["questions"],
                    "existing_answers": frozen["content"]["interview"],
                    "candidate": output,
                    "format_error": error,
                },
                ensure_ascii=False,
            ),
        ),
    ]


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
        allowed.update(
            "relationship:" + str(item.relationship_id) for item in content.relationships
        )
        allowed.update(
            "introduction:" + path for path, _, _ in content.introduction.source_fields()
        )
        for item in (*candidate.changes, *candidate.conflicts):
            if not set(item.source_refs) <= allowed:
                raise ValueError("Calibration references must belong to frozen input")
    return candidate


class AuthoringAgent:
    def __init__(self, budget: ModelBudget) -> None:
        self.budget = budget
        self.persona_guidance = (
            files("echo_commons")
            .joinpath("resources/authoring/persona-documents.md")
            .read_text(encoding="utf-8")
        )
        self.prompts = {
            operation: files("echo_commons")
            .joinpath(f"resources/authoring/{operation}.md")
            .read_text(encoding="utf-8")
            for operation in ("basic", "story", "interview", "calibrate")
        }
        self.interview_review = (
            files("echo_commons")
            .joinpath("resources/authoring/interview-review.md")
            .read_text(encoding="utf-8")
            + "\n只返回符合以下结构的一个 JSON 对象：\n"
            + json.dumps(InterviewOutput.model_json_schema(), ensure_ascii=False)
        )

    def prepare_prompt(self, operation: str, basis: dict | None) -> str:
        prompt = self.prompts[operation]
        if operation in ("basic", "calibrate"):
            prompt = self.persona_guidance + "\n\n" + prompt
        if operation == "interview":
            persona = render_persona(
                "", basis["profile"], basis["relational_dynamics"], basis["voice"]
            )
            identity = render_prompt_section(
                "character_identity",
                f"你叫{basis['display_name']}。\n{basis['description']}",
            )
            prompt = (
                identity
                + "\n\n"
                + "\n\n".join(render_prompt_section(name, body) for name, body in persona)
                + "\n\n"
                + prompt
            )
        schema = {
            "basic": BasicOutput,
            "story": StoryOutput,
            "interview": InterviewOutput,
            "calibrate": CalibrateOutput,
        }[operation].model_json_schema()
        return (
            prompt
            + "\n只返回符合以下结构的一个 JSON 对象：\n"
            + json.dumps(
                schema,
                ensure_ascii=False,
            )
        )

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
        prompt = frozen_input["prompt"]
        basis = frozen_input["interview_basis"]
        payload = {"request": frozen_input["request"], "content": frozen_input["content"]}
        if request.operation == "interview":
            payload = {
                "request": frozen_input["request"],
                "author_story": basis["story"],
                "author_relationships": basis.get("relationships", []),
                "introduction": basis.get("introduction", {}),
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
                model_profile=frozen_input["review_model_profile"]
                if request.operation == "interview" and index == 2
                else profile,
                attempt=1,
                step_index=index,
                messages=tuple(messages),
                output_contract=AUTHORING_CONTRACT,
                max_output_tokens=6000,
                reasoning_effort=frozen_input["review_reasoning_effort"]
                if request.operation == "interview" and index == 2
                else None,
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
                if request.operation == "interview" and index == 1:
                    messages = interview_review_messages(frozen_input, response.output, None)
                    continue
                return candidate
            except (ValidationError, ValueError) as error:
                if request.operation == "interview" and index == 1:
                    messages = interview_review_messages(frozen_input, response.output, str(error))
                    continue
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
