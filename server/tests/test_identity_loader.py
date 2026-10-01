from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from echo_commons.config import DEFAULT_IDENTITY_ROOT, load_settings
from echo_commons.services.identity import (
    IdentityConfigurationError,
    load_identity_catalog,
)

SERVER_ROOT = Path(__file__).parents[1]
IDENTITY_ROOT = SERVER_ROOT / "config" / "identity"


def test_identity_root_is_configurable_without_mutating_the_default(tmp_path) -> None:
    config = tmp_path / "settings.toml"
    source = SERVER_ROOT / "config" / "settings.toml"
    content = source.read_text(encoding="utf-8").replace(
        'root = "identity"', 'root = "C:/Echo/identity"'
    )
    config.write_text(content, encoding="utf-8")

    assert Path(load_settings(config).identity_root) == Path("C:/Echo/identity")
    assert str(IDENTITY_ROOT) == DEFAULT_IDENTITY_ROOT


def test_loader_returns_an_immutable_versioned_catalog() -> None:
    catalog = load_identity_catalog(IDENTITY_ROOT)

    assert catalog.schema_version == 2
    assert catalog.bundle_version == "0.4.0-draft"
    assert catalog.character_ids == ("xiaojin",)
    assert catalog.default_baseline.resource_id == "default-chat"
    assert catalog.default_baseline.content_version == "0.6.1-draft"
    character = catalog.character("xiaojin")
    assert character.content_version == "0.5.0-draft"
    assert character.profile.resource_id == "xiaojin.profile"
    assert character.voice is not None
    assert character.voice.resource_id == "xiaojin.voice"
    assert character.relational_dynamics is not None
    assert character.capabilities[0].name == "memory_search"
    assert character.memory_preload is not None
    assert [memory.memory_id for memory in character.memory_preload.memories] == [
        "xiaojin.preload.livelihood",
        "xiaojin.preload.home",
        "xiaojin.preload.painting-anchor",
        "xiaojin.preload.disappearance-secret",
    ]
    assert character.content.startswith("# 小槿 Profile")
    assert "## 变更日志" not in catalog.character("xiaojin").content
    assert catalog.baseline is catalog.default_baseline

    with pytest.raises(TypeError):
        catalog.characters["other"] = catalog.character("xiaojin")  # type: ignore[index]
    with pytest.raises(IdentityConfigurationError, match="not registered"):
        catalog.character("missing")


def test_missing_override_can_fall_back_to_a_packaged_or_test_root(tmp_path: Path) -> None:
    catalog = load_identity_catalog(
        tmp_path / "missing-identity",
        fallback_root=IDENTITY_ROOT,
    )

    assert catalog.character("xiaojin").resource_id == "xiaojin"


def test_existing_invalid_override_fails_closed(tmp_path: Path) -> None:
    override_root = tmp_path / "identity"
    shutil.copytree(IDENTITY_ROOT, override_root)
    manifest_path = override_root / "manifest.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "path: common/agent-contract.md", "path: ../manifest.yaml"
        ),
        encoding="utf-8",
    )

    with pytest.raises(IdentityConfigurationError, match="escapes"):
        load_identity_catalog(override_root, fallback_root=IDENTITY_ROOT)


def test_resource_metadata_must_match_manifest(tmp_path: Path) -> None:
    override_root = tmp_path / "identity"
    shutil.copytree(IDENTITY_ROOT, override_root)
    resource_path = override_root / "characters" / "xiaojin" / "profile.md"
    resource_path.write_text(
        resource_path.read_text(encoding="utf-8").replace(
            "resource_id: xiaojin.profile", "resource_id: other-character"
        ),
        encoding="utf-8",
    )

    with pytest.raises(IdentityConfigurationError, match="does not match manifest"):
        load_identity_catalog(override_root)
