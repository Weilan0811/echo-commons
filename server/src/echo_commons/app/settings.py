import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.modules.memory.domain.policy import MemoryPolicy

DEFAULT_SETTINGS_PATH = Path("config/settings.toml")
DEFAULT_MODEL_REGISTRY_PATH = Path("config/model-registry.toml")
DEFAULT_MODEL_SECRETS_PATH = Path("config/model-secrets.toml")
DEFAULT_DEBUG_CAPTURE_PATH = "data/debug-captures"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    memory: MemoryPolicy = Field(default_factory=MemoryPolicy)

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    cors_origins: tuple[str, ...] = ()
    database_path: str = "../data/echo-commons.sqlite3"
    identity_root: str | None = None
    model_registry_path: str = "model-registry.toml"
    model_secrets_path: str = "model-secrets.toml"
    asset_directory: str = "../data/assets/images"
    image_base_url: str = "https://api.apimart.ai/v1"
    image_model: str = "gpt-image-2"
    image_credential_ref: str = "apimart"
    image_concurrency: int = Field(default=1, ge=1)
    image_poll_interval_seconds: float = Field(default=5, gt=0)
    image_request_timeout_seconds: float = Field(default=30, gt=0)
    image_task_timeout_seconds: float = Field(default=900, gt=0)
    worker_enabled: bool = True
    worker_poll_interval_seconds: float = Field(default=0.25, gt=0)
    shutdown_timeout_seconds: float = Field(default=30, gt=0)
    model_concurrency: int = Field(default=3, ge=1)
    lease_seconds: float = Field(default=90, gt=0)
    lease_heartbeat_interval_seconds: float = Field(default=5, gt=0)
    lease_safety_margin_seconds: float = Field(default=2, ge=0)
    max_agent_attempts: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=1, ge=0)
    quiet_window_seconds: float = Field(default=6, ge=0)
    max_chain_messages: int = Field(default=3, ge=1)
    max_chain_tasks: int = Field(default=6, ge=1)
    recent_message_limit: int = Field(default=20, ge=1)
    recent_message_max_chars: int = Field(default=6000, ge=1)
    covered_message_overlap: int = Field(default=4, ge=0)
    resident_memory_limit: int = Field(default=32, ge=1)
    memory_search_max_results: int = Field(default=5, ge=1, le=5)
    max_thought_length: int = Field(default=1000, ge=1)
    max_utterance_length: int = Field(default=2000, ge=1)
    conversation_temperature: float | None = Field(default=None, ge=0, le=2)
    conversation_top_p: float | None = Field(default=None, gt=0, le=1)
    conversation_max_output_tokens: int | None = Field(default=None, ge=1)
    reflection_temperature: float | None = Field(default=None, ge=0, le=2)
    reflection_top_p: float | None = Field(default=None, gt=0, le=1)
    reflection_max_output_tokens: int | None = Field(default=None, ge=1)
    reflection_max_model_steps: int = Field(default=4, ge=1)
    reflection_max_model_requests: int = Field(default=4, ge=1)
    reflection_execution_timeout_seconds: float = Field(default=300, gt=0)
    reflection_max_materials: int = Field(default=256, ge=1)
    reflection_max_material_chars: int = Field(default=20000, ge=1)
    reflection_max_messages_per_segment: int = Field(default=100, ge=1)
    reflection_max_candidates: int = Field(default=64, ge=1)
    reflection_max_output_chars: int = Field(default=20000, ge=1)
    reflection_initialization_max_candidates: int = Field(default=256, ge=3)
    reflection_initialization_max_output_chars: int = Field(default=160000, ge=1)
    reflection_initialization_chars_per_input_char: int = Field(default=6, ge=1)
    reflection_initialization_candidates_per_material: int = Field(default=8, ge=1)
    reflection_core_memory_max_chars: int = Field(default=600, ge=1, le=6000)
    log_level: str = "INFO"
    log_path: str | None = None
    log_max_bytes: int = Field(default=5242880, ge=1)
    log_backup_count: int = Field(default=3, ge=0)
    debug_capture_enabled: bool = False
    debug_capture_path: str = "../data/debug-captures"
    trace_retry_backoff_seconds: float = Field(default=1, ge=0)
    trace_max_attempts: int = Field(default=5, ge=1)
    trace_lease_seconds: float = Field(default=30, gt=0)
    trace_batch_size: int = Field(default=25, ge=1)


_SECTION_FIELDS = {
    "memory": ("vector", "retrieval", "cycles"),
    "server": ("environment", "host", "port", "cors_origins"),
    "storage": ("database_path", "asset_directory"),
    "images": (
        "base_url",
        "model",
        "credential_ref",
        "concurrency",
        "poll_interval_seconds",
        "request_timeout_seconds",
        "task_timeout_seconds",
    ),
    "identity": ("root",),
    "model": ("registry_path", "secrets_path"),
    "workers": (
        "enabled",
        "poll_interval_seconds",
        "shutdown_timeout_seconds",
        "model_concurrency",
    ),
    "task": (
        "lease_seconds",
        "lease_heartbeat_interval_seconds",
        "lease_safety_margin_seconds",
        "max_agent_attempts",
        "retry_backoff_seconds",
    ),
    "social": ("quiet_window_seconds", "max_chain_messages", "max_chain_tasks"),
    "context": (
        "recent_message_limit",
        "recent_message_max_chars",
        "covered_message_overlap",
        "resident_memory_limit",
        "memory_search_max_results",
    ),
    "conversation": ("max_thought_length", "max_utterance_length", "generation"),
    "reflection": (
        "max_model_steps",
        "max_model_requests",
        "execution_timeout_seconds",
        "max_materials",
        "max_material_chars",
        "max_messages_per_segment",
        "max_candidates",
        "max_output_chars",
        "initialization_max_candidates",
        "initialization_max_output_chars",
        "initialization_chars_per_input_char",
        "initialization_candidates_per_material",
        "core_memory_max_chars",
        "generation",
    ),
    "observability": (
        "log_level",
        "log_path",
        "log_max_bytes",
        "log_backup_count",
        "debug_capture_enabled",
        "debug_capture_path",
        "trace_retry_backoff_seconds",
        "trace_max_attempts",
        "trace_lease_seconds",
        "trace_batch_size",
    ),
}


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> Settings:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    if config.pop("schema_version", None) != 1:
        raise ValueError("unsupported settings schema_version")
    values = {}
    renames = {
        "identity": {"root": "identity_root"},
        "model": {"registry_path": "model_registry_path", "secrets_path": "model_secrets_path"},
        "workers": {
            "enabled": "worker_enabled",
            "poll_interval_seconds": "worker_poll_interval_seconds",
        },
    }
    for section, options in config.items():
        if section not in _SECTION_FIELDS or not isinstance(options, dict):
            raise ValueError(f"unknown settings section: {section}")
        if section == "memory":
            values["memory"] = options
            continue
        for key, value in options.items():
            if key not in _SECTION_FIELDS[section]:
                raise ValueError(f"unknown setting in section: {section}.{key}")
            if key == "generation":
                if not isinstance(value, dict) or not value.keys() <= {
                    "temperature",
                    "top_p",
                    "max_output_tokens",
                }:
                    raise ValueError(f"invalid generation settings: {section}.generation")
                values.update({f"{section}_{name}": parameter for name, parameter in value.items()})
            else:
                target = renames.get(section, {}).get(key, key)
                if section == "images":
                    target = f"image_{key}"
                if section == "reflection":
                    target = f"reflection_{key}"
                if target in values:
                    raise ValueError(f"duplicate setting: {target}")
                values[target] = value
    settings = Settings.model_validate(values)
    paths = {}
    for key in (
        "database_path",
        "asset_directory",
        "identity_root",
        "model_registry_path",
        "model_secrets_path",
        "log_path",
        "debug_capture_path",
    ):
        value = getattr(settings, key)
        if value is not None:
            paths[key] = str((config_path.parent / Path(value).expanduser()).resolve())
    settings = settings.model_copy(update=paths)
    if (
        settings.lease_heartbeat_interval_seconds
        >= settings.lease_seconds - settings.lease_safety_margin_seconds
    ):
        raise ValueError("lease heartbeat must fit before lease expiry")
    return settings
