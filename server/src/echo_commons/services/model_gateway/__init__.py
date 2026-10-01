"""Model Gateway ports, providers and deterministic test doubles."""

from echo_server.services.model_gateway.errors import (
    classify_configuration_error,
    classify_provider_error,
)
from echo_server.services.model_gateway.fake import FakeModelGateway
from echo_server.services.model_gateway.metrics import ProviderUsageTracker
from echo_server.services.model_gateway.openai_compatible import (
    OpenAICompatibleGateway,
    normalize_completion,
    normalize_usage,
)
from echo_server.services.model_gateway.protocol import (
    ModelGateway,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelResponseKind,
    PromptMessage,
    ToolCall,
)
from echo_server.services.model_gateway.registry import (
    ModelConfigurationError,
    ModelCredentialError,
    ModelEntry,
    ModelRegistry,
    load_model_registry,
)
from echo_server.services.model_gateway.routing import (
    LIGHT_PROFILE,
    STRONG_PROFILE,
    ModelRoute,
    TaskRouting,
    resolve_agent_route,
)

__all__ = [
    "FakeModelGateway",
    "OpenAICompatibleGateway",
    "ProviderUsageTracker",
    "classify_configuration_error",
    "classify_provider_error",
    "ModelConfigurationError",
    "ModelCredentialError",
    "ModelEntry",
    "ModelRegistry",
    "load_model_registry",
    "normalize_completion",
    "normalize_usage",
    "ModelGateway",
    "ModelGatewayError",
    "ModelRequest",
    "ModelResponse",
    "ModelResponseKind",
    "PromptMessage",
    "ToolCall",
    "LIGHT_PROFILE",
    "STRONG_PROFILE",
    "ModelRoute",
    "TaskRouting",
    "resolve_agent_route",
]
