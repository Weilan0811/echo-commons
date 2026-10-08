from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml
from pydantic import ValidationError

from echo_commons.modules.characters.domain.state import InitialState
from echo_commons.modules.characters.templates.catalog import (
    AuthoredMemory,
    BlueprintCatalog,
    CapabilitiesResource,
    CharacterBlueprint,
    IdentityCapability,
    IdentityResource,
    MemoryPreloadResource,
)

IDENTITY_SCHEMA_VERSION = 1

CONTENT_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
SUPPORTED_RESOURCE_TYPES = frozenset(
    {
        "agent_contract",
        "character_profile",
        "character_voice",
        "relational_dynamics",
        "character_memory_preload",
    }
)
SUPPORTED_STATUSES = frozenset({"draft", "active", "retired"})
_MANIFEST_KEYS = frozenset({"schema_version", "bundle_version", "agent_contract", "blueprints"})
_RESOURCE_KEYS = frozenset(
    {
        "schema_version",
        "resource_type",
        "resource_id",
        "content_version",
        "status",
        "locale",
        "source_ref",
        "updated_at",
    }
)
_MANIFEST_RESOURCE_KEYS = frozenset({"resource_id", "path"})
_CHARACTER_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "resource_type",
        "resource_id",
        "display_name",
        "avatar_url",
        "content_version",
        "status",
        "locale",
        "source_ref",
        "updated_at",
        "profile",
        "voice",
        "relational_dynamics",
        "capabilities",
        "memory_preload",
        "initial_state",
    }
)
_CAPABILITIES_KEYS = _RESOURCE_KEYS | {"capabilities"}
_CAPABILITY_ITEM_KEYS = frozenset({"name", "description", "parameters", "action_kind"})
_MEMORY_PRELOAD_KEYS = _RESOURCE_KEYS | {"memories"}
_MEMORY_PRELOAD_ITEM_KEYS = frozenset(
    {
        "memory_id",
        "memory_kind",
        "content",
        "visibility",
        "confidence",
        "salience",
        "subject_kind",
        "subject_id",
    }
)
_MEMORY_KINDS = frozenset({"fact", "event", "preference", "promise", "thread", "other"})
_MEMORY_VISIBILITIES = frozenset({"resident", "recallable", "private"})


class IdentityConfigurationError(RuntimeError):
    """Raised when an Identity root cannot be loaded safely."""

    code = "identity_configuration_invalid"


def load_blueprint_catalog(root: str | Path | None = None) -> BlueprintCatalog:
    selected = (
        Path(root)
        if root is not None
        else Path(resources.files("echo_commons").joinpath("resources/identity"))
    )
    if not selected.is_dir():
        raise IdentityConfigurationError("identity resource root is missing")
    return _load_root(selected)


def _load_root(root: Path) -> BlueprintCatalog:
    if not root.is_dir():
        raise IdentityConfigurationError("identity resource root is not a directory")

    root = root.resolve()
    manifest_path = _resolve_file_path(root, "manifest.yaml", kind="manifest")
    manifest = _read_yaml_mapping(manifest_path, "identity manifest")
    _reject_unknown_keys(manifest, _MANIFEST_KEYS, "identity manifest")
    schema_version = _required_int(manifest, "schema_version", "identity manifest")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise IdentityConfigurationError("unsupported identity manifest schema version")
    bundle_version = _required_content_version(manifest, "bundle_version", "identity manifest")

    baseline_spec = _required_mapping(manifest, "agent_contract", "identity manifest")
    baseline_id, baseline_path = _resource_spec(baseline_spec, "agent_contract")
    baseline = _load_resource(
        root,
        relative_path=baseline_path,
        expected_types=("agent_contract",),
        expected_id=baseline_id,
    )

    characters_raw = _required_mapping(manifest, "blueprints", "identity manifest")
    characters: dict[str, CharacterBlueprint] = {}
    resolved_paths = {baseline.relative_path}
    resource_ids = {baseline.resource_id}
    for character_key, raw_spec in characters_raw.items():
        if not isinstance(character_key, str) or not character_key.strip():
            raise IdentityConfigurationError("character manifest key must be a non-empty string")
        spec = _mapping(raw_spec, f"characters.{character_key}")
        resource_id, relative_path = _resource_spec(spec, f"characters.{character_key}")
        if resource_id.startswith("custom:"):
            raise IdentityConfigurationError("custom: is reserved for database blueprints")
        if resource_id != character_key:
            raise IdentityConfigurationError("character manifest key does not match resource_id")
        if relative_path in resolved_paths:
            raise IdentityConfigurationError("identity manifest contains a duplicate resource path")

        character = _load_character_manifest(
            root,
            relative_path=relative_path,
            expected_id=resource_id,
        )
        if character.resource_id in resource_ids:
            raise IdentityConfigurationError("identity manifest contains a duplicate resource_id")
        characters[character_key] = character
        resolved_paths.add(relative_path)
        resource_ids.add(character.resource_id)

    return BlueprintCatalog(
        schema_version=schema_version,
        bundle_version=bundle_version,
        agent_contract=baseline,
        blueprints=characters,
    )


def _load_character_manifest(
    root: Path,
    *,
    relative_path: str,
    expected_id: str,
) -> CharacterBlueprint:
    path = _resolve_file_path(root, relative_path, kind="character manifest")
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise IdentityConfigurationError("character manifest must be YAML")
    manifest = _read_yaml_mapping(path, "character manifest")
    _reject_unknown_keys(manifest, _CHARACTER_MANIFEST_KEYS, "character manifest")
    schema_version = _required_int(manifest, "schema_version", "character manifest")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise IdentityConfigurationError("unsupported character manifest schema version")
    resource_type = _required_string(manifest, "resource_type", "character manifest")
    resource_id = _required_string(manifest, "resource_id", "character manifest")
    content_version = _required_content_version(manifest, "content_version", "character manifest")
    status = _required_string(manifest, "status", "character manifest")
    locale = _required_string(manifest, "locale", "character manifest")
    updated_at = _required_string(manifest, "updated_at", "character manifest")
    source_ref = _optional_string(manifest, "source_ref", "character manifest")
    if resource_type != "character_blueprint":
        raise IdentityConfigurationError("character manifest resource_type is unsupported")
    if resource_id != expected_id:
        raise IdentityConfigurationError("character manifest resource_id does not match manifest")
    _validate_status_and_date(status, updated_at, "character manifest")

    parent_relative = PurePosixPath(relative_path).parent.as_posix()
    profile_spec = _required_mapping(manifest, "profile", "character manifest")
    profile_id, profile_path = _resource_spec(profile_spec, "character manifest.profile")
    profile = _load_resource(
        root,
        relative_path=_child_path(parent_relative, profile_path),
        expected_types=("character_profile",),
        expected_id=profile_id,
    )

    relation_spec = _required_mapping(manifest, "relational_dynamics", "character manifest")
    relation_id, relation_path = _resource_spec(
        relation_spec,
        "character manifest.relational_dynamics",
    )
    relational_dynamics = _load_resource(
        root,
        relative_path=_child_path(parent_relative, relation_path),
        expected_types=("relational_dynamics",),
        expected_id=relation_id,
    )

    voice_spec = _required_mapping(manifest, "voice", "character manifest")
    voice_id, voice_path = _resource_spec(voice_spec, "character manifest.voice")
    voice = _load_resource(
        root,
        relative_path=_child_path(parent_relative, voice_path),
        expected_types=("character_voice",),
        expected_id=voice_id,
    )

    capabilities_spec = _required_mapping(manifest, "capabilities", "character manifest")
    capabilities_id, capabilities_path = _resource_spec(
        capabilities_spec,
        "character manifest.capabilities",
    )
    capabilities = _load_capabilities_resource(
        root,
        relative_path=_child_path(parent_relative, capabilities_path),
        expected_id=capabilities_id,
    )
    memory_preload = None
    if "memory_preload" in manifest:
        preload_spec = _required_mapping(manifest, "memory_preload", "character manifest")
        preload_id, preload_path = _resource_spec(
            preload_spec,
            "character manifest.memory_preload",
        )
        memory_preload = _load_memory_preload_resource(
            root,
            relative_path=_child_path(parent_relative, preload_path),
            expected_id=preload_id,
            character_id=resource_id,
        )
    avatar_url = manifest.get("avatar_url")
    if avatar_url is not None and (not isinstance(avatar_url, str) or not avatar_url.strip()):
        raise IdentityConfigurationError("avatar_url must be a nonempty string or null")
    try:
        initial_state = InitialState.model_validate(manifest.get("initial_state", {}))
    except ValidationError as error:
        raise IdentityConfigurationError("Invalid character initial_state") from error
    return CharacterBlueprint(
        resource_id=resource_id,
        display_name=_required_string(manifest, "display_name", "character manifest"),
        avatar_url=avatar_url,
        initial_state=initial_state,
        content_version=content_version,
        status=status,
        locale=locale,
        updated_at=updated_at,
        profile=profile,
        voice=voice,
        relational_dynamics=relational_dynamics,
        capabilities_resource=capabilities,
        memory_preload=memory_preload,
        source_ref=source_ref,
        relative_path=relative_path,
    )


def _load_resource(
    root: Path,
    *,
    relative_path: str,
    expected_types: tuple[str, ...],
    expected_id: str,
) -> IdentityResource:
    safe_relative_path, path = _resolve_resource_path(root, relative_path)
    if path.suffix.lower() != ".md":
        raise IdentityConfigurationError("identity Markdown resources must use .md")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise IdentityConfigurationError("identity resource could not be read") from exc

    metadata, body = _read_frontmatter(lines, "identity resource")
    _reject_unknown_keys(metadata, _RESOURCE_KEYS, "identity resource frontmatter")
    schema_version = _required_int(metadata, "schema_version", "identity resource")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise IdentityConfigurationError("unsupported identity resource schema version")
    resource_type = _required_string(metadata, "resource_type", "identity resource")
    resource_id = _required_string(metadata, "resource_id", "identity resource")
    content_version = _required_content_version(metadata, "content_version", "identity resource")
    status = _required_string(metadata, "status", "identity resource")
    locale = _required_string(metadata, "locale", "identity resource")
    updated_at = _required_string(metadata, "updated_at", "identity resource")
    source_ref = _optional_string(metadata, "source_ref", "identity resource")

    if resource_type not in expected_types:
        raise IdentityConfigurationError("identity resource_type does not match manifest")
    if resource_id != expected_id:
        raise IdentityConfigurationError("identity resource_id does not match manifest")
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise IdentityConfigurationError("identity resource_type is unsupported")
    _validate_status_and_date(status, updated_at, "identity resource")
    if "## 变更日志" in body:
        raise IdentityConfigurationError("identity resource body must not contain a changelog")

    return IdentityResource(
        schema_version=schema_version,
        resource_type=resource_type,
        resource_id=resource_id,
        content_version=content_version,
        status=status,
        locale=locale,
        updated_at=updated_at,
        content=body,
        source_ref=source_ref,
        relative_path=safe_relative_path,
    )


def _load_capabilities_resource(
    root: Path,
    *,
    relative_path: str,
    expected_id: str,
) -> CapabilitiesResource:
    safe_relative_path, path = _resolve_resource_path(root, relative_path)
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise IdentityConfigurationError("capabilities resource must be YAML")
    metadata = _read_yaml_mapping(path, "capabilities resource")
    _reject_unknown_keys(metadata, _CAPABILITIES_KEYS, "capabilities resource")
    schema_version = _required_int(metadata, "schema_version", "capabilities resource")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise IdentityConfigurationError("unsupported capabilities resource schema version")
    resource_type = _required_string(metadata, "resource_type", "capabilities resource")
    resource_id = _required_string(metadata, "resource_id", "capabilities resource")
    content_version = _required_content_version(
        metadata,
        "content_version",
        "capabilities resource",
    )
    status = _required_string(metadata, "status", "capabilities resource")
    locale = _required_string(metadata, "locale", "capabilities resource")
    updated_at = _required_string(metadata, "updated_at", "capabilities resource")
    source_ref = _optional_string(metadata, "source_ref", "capabilities resource")
    if resource_type != "character_capabilities":
        raise IdentityConfigurationError("capabilities resource_type is unsupported")
    if resource_id != expected_id:
        raise IdentityConfigurationError("capabilities resource_id does not match manifest")
    _validate_status_and_date(status, updated_at, "capabilities resource")
    raw_capabilities = metadata.get("capabilities")
    if not isinstance(raw_capabilities, list):
        raise IdentityConfigurationError("capabilities resource.capabilities must be a list")
    capabilities: list[IdentityCapability] = []
    names: set[str] = set()
    for index, raw_capability in enumerate(raw_capabilities):
        item = _mapping(raw_capability, f"capabilities resource.capabilities[{index}]")
        _reject_unknown_keys(
            item,
            _CAPABILITY_ITEM_KEYS,
            f"capabilities resource.capabilities[{index}]",
        )
        name = _required_string(item, "name", "capability")
        description = _required_string(item, "description", "capability")
        action_kind = _required_string(item, "action_kind", "capability")
        if action_kind not in {"read", "proposal", "external"}:
            raise IdentityConfigurationError("capability action_kind is unsupported")
        parameters = item.get("parameters", {})
        if not isinstance(parameters, dict):
            raise IdentityConfigurationError("capability parameters must be a mapping")
        if name in names:
            raise IdentityConfigurationError("capability names must be unique")
        names.add(name)
        capabilities.append(
            IdentityCapability(
                name=name,
                description=description,
                parameters_json=json.dumps(parameters, ensure_ascii=False),
                action_kind=action_kind,
            )
        )
    return CapabilitiesResource(
        schema_version=schema_version,
        resource_type=resource_type,
        resource_id=resource_id,
        content_version=content_version,
        status=status,
        locale=locale,
        updated_at=updated_at,
        capabilities=tuple(capabilities),
        source_ref=source_ref,
        relative_path=safe_relative_path,
    )


def _load_memory_preload_resource(
    root: Path,
    *,
    relative_path: str,
    expected_id: str,
    character_id: str,
) -> MemoryPreloadResource:
    safe_relative_path, path = _resolve_resource_path(root, relative_path)
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise IdentityConfigurationError("memory preload resource must be YAML")
    metadata = _read_yaml_mapping(path, "memory preload resource")
    _reject_unknown_keys(metadata, _MEMORY_PRELOAD_KEYS, "memory preload resource")
    schema_version = _required_int(metadata, "schema_version", "memory preload resource")
    if schema_version != IDENTITY_SCHEMA_VERSION:
        raise IdentityConfigurationError("unsupported memory preload resource schema version")
    resource_type = _required_string(metadata, "resource_type", "memory preload resource")
    resource_id = _required_string(metadata, "resource_id", "memory preload resource")
    content_version = _required_content_version(
        metadata,
        "content_version",
        "memory preload resource",
    )
    status = _required_string(metadata, "status", "memory preload resource")
    locale = _required_string(metadata, "locale", "memory preload resource")
    updated_at = _required_string(metadata, "updated_at", "memory preload resource")
    source_ref = _optional_string(metadata, "source_ref", "memory preload resource")
    if resource_type != "character_memory_preload":
        raise IdentityConfigurationError("memory preload resource_type is unsupported")
    if resource_id != expected_id:
        raise IdentityConfigurationError("memory preload resource_id does not match manifest")
    _validate_status_and_date(status, updated_at, "memory preload resource")
    raw_memories = metadata.get("memories")
    if not isinstance(raw_memories, list):
        raise IdentityConfigurationError("memory preload resource.memories must be a list")
    memories: list[AuthoredMemory] = []
    memory_ids: set[str] = set()
    for index, raw_memory in enumerate(raw_memories):
        item = _mapping(raw_memory, f"memory preload resource.memories[{index}]")
        _reject_unknown_keys(
            item,
            _MEMORY_PRELOAD_ITEM_KEYS,
            f"memory preload resource.memories[{index}]",
        )
        memory_id = _required_string(item, "memory_id", "authored memory")
        if memory_id in memory_ids:
            raise IdentityConfigurationError("memory preload memory_id values must be unique")
        memory_ids.add(memory_id)
        memory_kind = _required_string(item, "memory_kind", "authored memory")
        if memory_kind not in _MEMORY_KINDS:
            raise IdentityConfigurationError("authored memory_kind is unsupported")
        content = _required_string(item, "content", "authored memory")
        visibility = _required_string(item, "visibility", "authored memory")
        if visibility not in _MEMORY_VISIBILITIES:
            raise IdentityConfigurationError("authored memory visibility is unsupported")
        confidence = _optional_ratio(item, "confidence", "authored memory", default=1.0)
        salience = _optional_ratio(item, "salience", "authored memory", default=0.5)
        subject_kind = _optional_string(item, "subject_kind", "authored memory") or "self"
        subject_id = _optional_string(item, "subject_id", "authored memory") or "self"
        memories.append(
            AuthoredMemory(
                memory_id=memory_id,
                memory_kind=memory_kind,
                content=content,
                visibility=visibility,
                confidence=confidence,
                salience=salience,
                subject_kind=subject_kind,
                subject_id=subject_id,
            )
        )
    return MemoryPreloadResource(
        schema_version=schema_version,
        resource_type=resource_type,
        resource_id=resource_id,
        content_version=content_version,
        status=status,
        locale=locale,
        updated_at=updated_at,
        memories=tuple(memories),
        source_ref=source_ref,
        relative_path=safe_relative_path,
    )


def _resource_spec(spec: Mapping[str, object], name: str) -> tuple[str, str]:
    _reject_unknown_keys(spec, _MANIFEST_RESOURCE_KEYS, name)
    resource_id = _required_string(spec, "resource_id", name)
    path = _required_string(spec, "path", name)
    return resource_id, path


def _resolve_resource_path(root: Path, relative_path: str) -> tuple[str, Path]:
    path = _resolve_file_path(root, relative_path, kind="resource")
    return PurePosixPath(relative_path).as_posix(), path


def _resolve_file_path(root: Path, relative_path: str, *, kind: str) -> Path:
    if not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise IdentityConfigurationError(f"identity {kind} path must be canonical relative path")
    if PurePosixPath(relative_path).is_absolute() or PureWindowsPath(relative_path).is_absolute():
        raise IdentityConfigurationError(f"identity {kind} path must be relative")
    parts = PurePosixPath(relative_path).parts
    if ".." in parts:
        raise IdentityConfigurationError(f"identity {kind} path escapes the resource root")
    if not parts or any(part in {"", "."} for part in parts):
        raise IdentityConfigurationError(f"identity {kind} path is not normalized")
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != relative_path:
        raise IdentityConfigurationError(f"identity {kind} path is not normalized")

    root_resolved = root.resolve()
    path = (root / Path(*parts)).resolve()
    if not path.is_relative_to(root_resolved):
        raise IdentityConfigurationError(f"identity {kind} path escapes the resource root")
    if not path.is_file():
        raise IdentityConfigurationError(f"identity {kind} file is missing")
    return path


def _child_path(parent: str, child: str) -> str:
    if not child or PurePosixPath(child).is_absolute() or PureWindowsPath(child).is_absolute():
        raise IdentityConfigurationError("character resource path must be relative")
    if "\\" in child or "\x00" in child or ".." in PurePosixPath(child).parts:
        raise IdentityConfigurationError("character resource path must stay inside its bundle")
    parts = (*PurePosixPath(parent).parts, *PurePosixPath(child).parts)
    return PurePosixPath(*parts).as_posix()


def _read_frontmatter(lines: list[str], name: str) -> tuple[dict[str, object], str]:
    if not lines or lines[0] != "---":
        raise IdentityConfigurationError(f"{name} is missing YAML frontmatter")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise IdentityConfigurationError(f"{name} frontmatter is not closed") from exc
    metadata = _mapping(
        _safe_load("\n".join(lines[1:closing_index]), f"{name} frontmatter"),
        f"{name} frontmatter",
    )
    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        raise IdentityConfigurationError(f"{name} body is empty")
    return metadata, body


def _read_yaml_mapping(path: Path, name: str) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise IdentityConfigurationError(f"{name} could not be read") from exc
    return _mapping(_safe_load(text, name), name)


def _safe_load(text: str, name: str) -> object:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise IdentityConfigurationError(f"{name} is not valid YAML") from exc


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IdentityConfigurationError(f"{name} must be a YAML mapping")
    return value


def _required_mapping(values: Mapping[str, object], key: str, name: str) -> dict[str, object]:
    return _mapping(values.get(key), f"{name}.{key}")


def _reject_unknown_keys(values: Mapping[str, object], allowed: frozenset[str], name: str) -> None:
    if any(not isinstance(key, str) or key not in allowed for key in values):
        raise IdentityConfigurationError(f"{name} contains an unsupported field")


def _required_int(values: Mapping[str, object], key: str, name: str) -> int:
    value = values.get(key)
    if type(value) is not int:
        raise IdentityConfigurationError(f"{name}.{key} must be an integer")
    return value


def _required_string(values: Mapping[str, object], key: str, name: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IdentityConfigurationError(f"{name}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(values: Mapping[str, object], key: str, name: str) -> str | None:
    if key not in values or values[key] is None:
        return None
    return _required_string(values, key, name)


def _optional_ratio(
    values: Mapping[str, object],
    key: str,
    name: str,
    *,
    default: float,
) -> float:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IdentityConfigurationError(f"{name}.{key} must be a number between 0 and 1")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise IdentityConfigurationError(f"{name}.{key} must be a number between 0 and 1")
    return numeric


def _required_content_version(values: Mapping[str, object], key: str, name: str) -> str:
    value = _required_string(values, key, name)
    if CONTENT_VERSION_PATTERN.fullmatch(value) is None:
        raise IdentityConfigurationError(f"{name}.{key} is not a content version")
    return value


def _validate_status_and_date(status: str, updated_at: str, name: str) -> None:
    if status not in SUPPORTED_STATUSES:
        raise IdentityConfigurationError(f"{name} resource status is unsupported")
    try:
        date.fromisoformat(updated_at)
    except ValueError as exc:
        raise IdentityConfigurationError(f"{name} updated_at is not an ISO date") from exc
