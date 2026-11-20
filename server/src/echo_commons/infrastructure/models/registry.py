from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlparse

from pydantic import ValidationError

from echo_commons.app.settings import DEFAULT_MODEL_REGISTRY_PATH, DEFAULT_MODEL_SECRETS_PATH
from echo_commons.infrastructure.models.decision_protocol import DecisionPolicy
from echo_commons.infrastructure.models.routing import (
    LIGHT_PROFILE,
    STRONG_PROFILE,
    ModelRoute,
    TaskRouting,
)


class ModelConfigurationError(RuntimeError):
    """Raised when the local model registry cannot be used safely."""

    code = "model_configuration_invalid"


class ModelCredentialError(ModelConfigurationError):
    """Raised when a selected model has no local credential."""

    code = "provider_not_configured"


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """One model and the endpoint currently used to reach it."""

    entry_id: str
    model_vendor: str
    model: str
    base_url: str
    credential_ref: str | None
    access_route: str
    protocol: str = "openai_compatible"
    enabled: bool = True
    request_timeout_seconds: float = 25.0
    max_retries: int = 1
    retry_backoff_seconds: float = 0.5
    max_output_tokens: int = 512
    context_window_tokens: int = 131072
    token_counter: str = "utf8_bytes"
    temperature: float | None = None
    top_p: float | None = None
    response_format: str = "json_object"
    extra_body: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entry_id or not self.model_vendor or not self.model:
            raise ModelConfigurationError("model entry identifiers must be non-empty")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ModelConfigurationError("model entry base_url must be an HTTP(S) URL")
        if self.protocol not in {"openai_compatible", "startlux_decision"}:
            raise ModelConfigurationError("model entry protocol is invalid")
        if not self.access_route or (
            self.protocol == "openai_compatible" and not self.credential_ref
        ):
            raise ModelConfigurationError("model entry route and credential must be named")
        if self.request_timeout_seconds <= 0:
            raise ModelConfigurationError("model request timeout must be positive")
        if self.max_retries < 0:
            raise ModelConfigurationError("model max_retries must not be negative")
        if self.retry_backoff_seconds < 0:
            raise ModelConfigurationError("model retry backoff must not be negative")
        if self.max_output_tokens < 1:
            raise ModelConfigurationError("model max_output_tokens must be positive")
        if self.context_window_tokens <= self.max_output_tokens:
            raise ModelConfigurationError("context window must exceed output reservation")
        if self.token_counter not in {"utf8_bytes", "cl100k_base", "o200k_base"}:
            raise ModelConfigurationError("unsupported model token counter")
        if self.response_format not in {"", "json_object"}:
            raise ModelConfigurationError("only json_object response format is supported")


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Validated model routing without environment-variable model switches."""

    backend: str
    active_profile: str
    profiles: Mapping[str, str]
    entries: Mapping[str, ModelEntry]
    credentials: Mapping[str, str]
    task_profiles: Mapping[str, str] = field(default_factory=dict)
    strong_enabled: bool = False
    decision: DecisionPolicy = field(default_factory=DecisionPolicy)

    def __post_init__(self) -> None:
        if self.backend not in {"openai_compatible"}:
            raise ModelConfigurationError("runtime backend is invalid")
        if not self.active_profile:
            raise ModelConfigurationError("active model profile must be named")
        if not isinstance(self.strong_enabled, bool):
            raise ModelConfigurationError("routing.strong_enabled must be a boolean")
        for profile, entry_id in self.profiles.items():
            if not profile or not entry_id:
                raise ModelConfigurationError("model profiles must map non-empty names")
            if entry_id not in self.entries:
                raise ModelConfigurationError(f"model profile points to unknown entry: {profile}")
        for task_kind, profile in self.task_profiles.items():
            if not task_kind or not profile:
                raise ModelConfigurationError("task routes must map non-empty names")
            if profile not in self.profiles and not (
                profile == STRONG_PROFILE and not self.strong_enabled
            ):
                message = f"task route points to unknown profile: {task_kind}"
                raise ModelConfigurationError(message)
        if (
            not self.strong_enabled
            and (
                self.active_profile == STRONG_PROFILE
                or STRONG_PROFILE in self.task_profiles.values()
            )
            and LIGHT_PROFILE not in self.profiles
        ):
            raise ModelConfigurationError(
                "light profile is required when strong routing is disabled"
            )
        if self.decision.enabled:
            entry = self.resolve(self.decision.profile)
            if entry.protocol != "startlux_decision":
                raise ModelConfigurationError(
                    "decision profile requires startlux_decision protocol"
                )

    def resolve(self, profile: str | None = None, entry_id: str | None = None) -> ModelEntry:
        if not self.strong_enabled and (profile or self.active_profile) == STRONG_PROFILE:
            profile = LIGHT_PROFILE
        selected_entry_id = entry_id
        if selected_entry_id is None:
            selected_entry_id = self.profiles.get(profile or self.active_profile)
        if selected_entry_id is None:
            raise ModelConfigurationError("model profile is not configured")
        entry = self.entries.get(selected_entry_id)
        if entry is None:
            raise ModelConfigurationError("model entry is not configured")
        if not entry.enabled:
            raise ModelConfigurationError("model entry is disabled")
        return entry

    def credential_for(self, entry: ModelEntry) -> str | None:
        credential = self.credentials.get(entry.credential_ref)
        if credential is None:
            return None
        value = credential.strip()
        return value or None

    @property
    def task_routing(self) -> TaskRouting:
        """Return the immutable task routing policy for constructed Agents."""

        return TaskRouting(
            default_profile=self.active_profile,
            task_profiles=self.task_profiles,
            strong_enabled=self.strong_enabled,
        )

    def route_for(self, task_kind: str) -> ModelRoute:
        """Resolve a task's logical model profile from this registry."""

        return self.task_routing.route_for(task_kind)


def load_model_registry(
    registry_path: str | Path = DEFAULT_MODEL_REGISTRY_PATH,
    secrets_path: str | Path = DEFAULT_MODEL_SECRETS_PATH,
) -> ModelRegistry:
    """Load the committed registry and optional ignored credential file."""

    registry_data = _read_toml(Path(registry_path), required=True)
    if registry_data.get("schema_version") != 1:
        raise ModelConfigurationError("unsupported model registry schema_version")
    secrets_data = _read_toml(Path(secrets_path), required=False)

    runtime = _mapping(registry_data.get("runtime"), "runtime")
    gateway = _mapping(registry_data.get("gateway"), "gateway")
    routing = _mapping(registry_data.get("routing"), "routing")
    task_profiles_raw = _mapping(routing.get("task_profiles"), "routing.task_profiles")
    profiles_raw = _mapping(registry_data.get("profiles"), "profiles")
    entries_raw = _mapping(registry_data.get("entries"), "entries")
    credentials_raw = _mapping(secrets_data.get("credentials"), "credentials")
    try:
        decision = DecisionPolicy.model_validate(
            _mapping(registry_data.get("decision"), "decision")
        )
    except ValidationError as exc:
        raise ModelConfigurationError("decision configuration is invalid") from exc

    default_timeout = _positive_float(
        gateway.get("request_timeout_seconds", 25.0), "gateway.request_timeout_seconds"
    )
    default_retries = _non_negative_int(gateway.get("max_retries", 1), "gateway.max_retries")
    default_backoff = _non_negative_float(
        gateway.get("retry_backoff_seconds", 0.5), "gateway.retry_backoff_seconds"
    )
    default_output_tokens = _positive_int(
        gateway.get("max_output_tokens", 512), "gateway.max_output_tokens"
    )
    default_response_format = str(gateway.get("response_format", "json_object"))

    entries: dict[str, ModelEntry] = {}
    for entry_id, raw_entry in entries_raw.items():
        values = _mapping(raw_entry, f"entries.{entry_id}")
        entries[entry_id] = ModelEntry(
            entry_id=entry_id,
            model_vendor=_required_string(values, "model_vendor", entry_id),
            model=_required_string(values, "model", entry_id),
            base_url=_required_string(values, "base_url", entry_id).rstrip("/"),
            credential_ref=(
                None
                if values.get("protocol") == "startlux_decision"
                and values.get("credential_ref") is None
                else _required_string(values, "credential_ref", entry_id)
            ),
            access_route=_required_string(values, "access_route", entry_id),
            protocol=str(values.get("protocol", "openai_compatible")),
            enabled=_bool(values.get("enabled", True), f"entries.{entry_id}.enabled"),
            request_timeout_seconds=_positive_float(
                values.get("request_timeout_seconds", default_timeout),
                f"entries.{entry_id}.request_timeout_seconds",
            ),
            max_retries=_non_negative_int(
                values.get("max_retries", default_retries), f"entries.{entry_id}.max_retries"
            ),
            retry_backoff_seconds=_non_negative_float(
                values.get("retry_backoff_seconds", default_backoff),
                f"entries.{entry_id}.retry_backoff_seconds",
            ),
            max_output_tokens=_positive_int(
                values.get("max_output_tokens", default_output_tokens),
                f"entries.{entry_id}.max_output_tokens",
            ),
            context_window_tokens=_positive_int(
                values.get("context_window_tokens", 131072),
                f"entries.{entry_id}.context_window_tokens",
            ),
            token_counter=str(values.get("token_counter", "utf8_bytes")),
            temperature=_optional_float(
                values.get("temperature"), f"entries.{entry_id}.temperature"
            ),
            top_p=_optional_float(values.get("top_p"), f"entries.{entry_id}.top_p"),
            response_format=str(values.get("response_format", default_response_format)),
            extra_body=MappingProxyType(
                dict(_mapping(values.get("extra_body", {}), f"entries.{entry_id}.extra_body"))
            ),
        )

    profiles = {
        profile: _string(entry_id, f"profiles.{profile}")
        for profile, entry_id in profiles_raw.items()
    }
    credentials = {}
    for name, value in credentials_raw.items():
        if not isinstance(value, str):
            raise ModelConfigurationError(f"credentials.{name} must be a string")
        credentials[name] = value.strip()
    task_profiles = {
        _string(task_kind, f"routing.task_profiles.{task_kind}"): _string(
            profile, f"routing.task_profiles.{task_kind}"
        )
        for task_kind, profile in task_profiles_raw.items()
    }
    return ModelRegistry(
        backend=_string(runtime.get("backend", "openai_compatible"), "runtime.backend"),
        active_profile=_string(
            runtime.get("active_profile", LIGHT_PROFILE), "runtime.active_profile"
        ),
        profiles=MappingProxyType(profiles),
        entries=MappingProxyType(entries),
        credentials=MappingProxyType(credentials),
        task_profiles=MappingProxyType(task_profiles),
        strong_enabled=_bool(routing.get("strong_enabled", False), "routing.strong_enabled"),
        decision=decision,
    )


def _read_toml(path: Path, *, required: bool) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        if required:
            raise ModelConfigurationError("model registry file is missing") from None
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ModelConfigurationError("model configuration could not be read") from exc
    if not isinstance(data, dict):
        raise ModelConfigurationError("model configuration must be a TOML table")
    return data


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelConfigurationError(f"{name} must be a TOML table")
    return value


def _required_string(values: Mapping[str, object], key: str, entry_id: str) -> str:
    value = values.get(key)
    return _string(value, f"entries.{entry_id}.{key}")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ModelConfigurationError(f"{name} must be a boolean")
    return value


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ModelConfigurationError(f"{name} must be positive")
    return float(value)


def _non_negative_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ModelConfigurationError(f"{name} must not be negative")
    return float(value)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ModelConfigurationError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelConfigurationError(f"{name} must not be negative")
    return value


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelConfigurationError(f"{name} must be numeric")
    return float(value)
