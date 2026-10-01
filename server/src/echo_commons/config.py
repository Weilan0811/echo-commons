from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = SERVER_ROOT / "config" / "settings.toml"
DEFAULT_DATABASE_PATH = str(SERVER_ROOT / "data" / "echo.sqlite3")
DEFAULT_LOG_PATH = str(SERVER_ROOT / "data" / "logs" / "echo.log")
DEFAULT_MODEL_REGISTRY_PATH = str(SERVER_ROOT / "config" / "model-registry.toml")
DEFAULT_MODEL_SECRETS_PATH = str(SERVER_ROOT / "config" / "model-secrets.toml")
DEFAULT_IDENTITY_ROOT = str(SERVER_ROOT / "config" / "identity")
DEFAULT_DEBUG_CAPTURE_PATH = str(SERVER_ROOT / "data" / "debug-captures")


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    database_path: str = DEFAULT_DATABASE_PATH
    worker_enabled: bool = True
    worker_poll_interval_seconds: float = 0.25
    lease_seconds: float = 30.0
    lease_heartbeat_interval_seconds: float = 5.0
    max_agent_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    trace_retry_backoff_seconds: float = 1.0
    trace_max_attempts: int = 5
    trace_lease_seconds: float = 30.0
    trace_batch_size: int = 25
    quiet_window_seconds: int = 6
    max_thought_length: int = 1000
    max_utterance_length: int = 2000
    recent_message_limit: int = 20
    recent_message_max_chars: int = 6000
    covered_message_overlap: int = 4
    resident_memory_limit: int = 32
    memory_search_max_results: int = 5
    conversation_temperature: float | None = None
    conversation_top_p: float | None = None
    conversation_max_output_tokens: int | None = None
    reflection_temperature: float | None = None
    reflection_top_p: float | None = None
    reflection_max_output_tokens: int | None = None
    reflection_max_model_steps: int = 2
    reflection_max_model_requests: int = 2
    reflection_max_materials: int = 256
    reflection_max_material_chars: int = 20_000
    reflection_max_messages_per_segment: int = 100
    reflection_max_candidates: int = 64
    reflection_max_output_chars: int = 20_000
    account_id: str = "local-player"
    default_conversation_id: str = "xiaojin"
    default_character_id: str = "xiaojin"
    log_path: str | None = None
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 3
    debug_capture_enabled: bool = False
    debug_capture_path: str = DEFAULT_DEBUG_CAPTURE_PATH
    lease_safety_margin_seconds: float = 2.0
    model_registry_path: str = DEFAULT_MODEL_REGISTRY_PATH
    model_secrets_path: str = DEFAULT_MODEL_SECRETS_PATH
    identity_root: str = DEFAULT_IDENTITY_ROOT


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> Settings:
    config_path = Path(path).resolve()
    with config_path.open("rb") as file:
        config = tomllib.load(file)

    server = config["server"]
    storage = config["storage"]
    identity = config["identity"]
    worker = config["worker"]
    conversation = config["conversation"]
    reflection = config["reflection"]
    model = config["model"]
    observability = config["observability"]
    conversation_generation = conversation["generation"]
    reflection_generation = reflection["generation"]

    return Settings(
        environment=server["environment"],
        host=server["host"],
        port=server["port"],
        database_path=_resolve_path(storage["database_path"], config_path),
        account_id=identity["account_id"],
        default_conversation_id=identity["default_conversation_id"],
        default_character_id=identity["default_character_id"],
        identity_root=_resolve_path(identity["root"], config_path),
        worker_enabled=worker["enabled"],
        worker_poll_interval_seconds=worker["poll_interval_seconds"],
        lease_seconds=worker["lease_seconds"],
        lease_heartbeat_interval_seconds=worker["lease_heartbeat_interval_seconds"],
        max_agent_attempts=worker["max_agent_attempts"],
        retry_backoff_seconds=worker["retry_backoff_seconds"],
        lease_safety_margin_seconds=worker["lease_safety_margin_seconds"],
        quiet_window_seconds=conversation["quiet_window_seconds"],
        max_thought_length=conversation["max_thought_length"],
        max_utterance_length=conversation["max_utterance_length"],
        recent_message_limit=conversation["recent_message_limit"],
        recent_message_max_chars=conversation["recent_message_max_chars"],
        covered_message_overlap=conversation["covered_message_overlap"],
        resident_memory_limit=conversation["resident_memory_limit"],
        memory_search_max_results=conversation["memory_search_max_results"],
        conversation_temperature=conversation_generation.get("temperature"),
        conversation_top_p=conversation_generation.get("top_p"),
        conversation_max_output_tokens=conversation_generation.get("max_output_tokens"),
        reflection_temperature=reflection_generation.get("temperature"),
        reflection_top_p=reflection_generation.get("top_p"),
        reflection_max_output_tokens=reflection_generation.get("max_output_tokens"),
        reflection_max_model_steps=reflection.get("max_model_steps", 2),
        reflection_max_model_requests=reflection.get("max_model_requests", 2),
        reflection_max_materials=reflection["max_materials"],
        reflection_max_material_chars=reflection["max_material_chars"],
        reflection_max_messages_per_segment=reflection["max_messages_per_segment"],
        reflection_max_candidates=reflection["max_candidates"],
        reflection_max_output_chars=reflection["max_output_chars"],
        model_registry_path=_resolve_path(model["registry_path"], config_path),
        model_secrets_path=_resolve_path(model["secrets_path"], config_path),
        log_level=observability["log_level"].upper(),
        log_path=_resolve_path(observability["log_path"], config_path)
        if observability["log_path"]
        else None,
        log_max_bytes=observability["log_max_bytes"],
        log_backup_count=observability["log_backup_count"],
        debug_capture_enabled=observability["debug_capture_enabled"],
        debug_capture_path=_resolve_path(observability["debug_capture_path"], config_path),
        trace_retry_backoff_seconds=observability["trace_retry_backoff_seconds"],
        trace_max_attempts=observability["trace_max_attempts"],
        trace_lease_seconds=observability["trace_lease_seconds"],
        trace_batch_size=observability["trace_batch_size"],
    )


def _resolve_path(value: str, config_path: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return str(path.resolve())
