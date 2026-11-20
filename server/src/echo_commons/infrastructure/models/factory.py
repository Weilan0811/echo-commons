from dataclasses import replace

from openai import AsyncOpenAI

from .decision import DecisionGateway
from .image_contracts import ImageConfiguration
from .images import ImageGateway
from .protocol import ModelRequest
from .registry import ModelConfigurationError, ModelEntry

PROVIDER_ENDPOINTS = {
    "deepseek": "https://api.deepseek.com",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "minimax": "https://api.minimax.cn/v1",
}


def decision_gateway(registry, budget, *, debug_capture=None):
    enabled = replace(registry, decision=registry.decision.model_copy(update={"enabled": True}))
    return DecisionGateway(enabled, budget, debug_capture=debug_capture)


def image_gateway(settings, registry):
    return ImageGateway(
        ImageConfiguration(
            provider=settings.image_provider,
            model=settings.image_model,
            base_url=settings.image_base_url.rstrip("/"),
            credential_ref=settings.image_credential_ref,
        ),
        registry.credentials,
        settings.image_request_timeout_seconds,
    )


def text_client(entry: ModelEntry, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=entry.base_url,
        timeout=entry.request_timeout_seconds,
        max_retries=0,
    )


def text_options(entry: ModelEntry, request: ModelRequest) -> dict[str, object]:
    extra = dict(entry.extra_body)
    vendor = entry.model_vendor
    if vendor == "deepseek":
        extra.setdefault("thinking", {"type": "disabled"})
    if vendor in {"qwen", "dashscope"}:
        extra.setdefault("enable_thinking", False)
    if vendor == "minimax" and entry.model.startswith("MiniMax-M3"):
        if request.thinking is False:
            raise ModelConfigurationError("MiniMax M3 requires thinking mode")
        extra.setdefault("reasoning_split", True)
        extra.setdefault("reasoning_effort", "low")
        extra.pop("thinking", None)
    if request.reasoning_effort is not None:
        extra["reasoning_effort"] = request.reasoning_effort
    if request.thinking is not None and not (
        vendor == "minimax" and entry.model.startswith("MiniMax-M3")
    ):
        if vendor in {"qwen", "dashscope"}:
            extra["enable_thinking"] = request.thinking
            if request.thinking and request.max_thinking_tokens is not None:
                extra["thinking_budget"] = request.max_thinking_tokens
                extra.pop("reasoning_effort", None)
        else:
            extra["thinking"] = {"type": "enabled" if request.thinking else "disabled"}
    return {"extra_body": extra} if extra else {}


def supports_sampling(entry: ModelEntry, request: ModelRequest) -> bool:
    return not request.thinking and not (
        entry.model_vendor == "minimax" and entry.model.startswith("MiniMax-M3")
    )
