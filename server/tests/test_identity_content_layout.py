from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

SERVER_ROOT = Path(__file__).parents[1]
IDENTITY_ROOT = SERVER_ROOT / "config" / "identity"
FIXTURE_ROOT = SERVER_ROOT / "tests" / "fixtures" / "identity"
CONTENT_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _as_mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _read_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---"

    closing_index = lines.index("---", 1)
    metadata = _as_mapping(yaml.safe_load("\n".join(lines[1:closing_index])))

    body = "\n".join(lines[closing_index + 1 :])
    return metadata, body


def _read_yaml_mapping(path: Path) -> dict[str, object]:
    return _as_mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_runtime_identity_resources_have_stable_metadata_and_boundaries() -> None:
    resources = (
        (
            IDENTITY_ROOT / "common" / "agent-contract.md",
            "agent_contract",
            "default-chat",
            "0.6.1-draft",
        ),
        (
            IDENTITY_ROOT / "characters" / "xiaojin" / "profile.md",
            "character_profile",
            "xiaojin.profile",
            "0.5.0-draft",
        ),
        (
            IDENTITY_ROOT / "characters" / "xiaojin" / "voice.md",
            "character_voice",
            "xiaojin.voice",
            "0.1.0-draft",
        ),
        (
            IDENTITY_ROOT / "characters" / "xiaojin" / "relational-dynamics.md",
            "relational_dynamics",
            "xiaojin.relational-dynamics",
            "0.2.0-draft",
        ),
    )

    for path, resource_type, resource_id, content_version in resources:
        metadata, body = _read_frontmatter(path)
        assert metadata["schema_version"] == 2
        assert metadata["resource_type"] == resource_type
        assert metadata["resource_id"] == resource_id
        assert metadata["content_version"] == content_version
        assert metadata["status"] == "draft"
        assert metadata["locale"] == "zh-CN"
        assert isinstance(metadata["updated_at"], str)
        date.fromisoformat(metadata["updated_at"])
        assert CONTENT_VERSION_PATTERN.fullmatch(metadata["content_version"])
        assert not {
            "baseline_version",
            "identity_version",
            "character",
            "updated",
            "notes",
        }.intersection(metadata)
        assert body.strip()
        assert "## 变更日志" not in body


def test_identity_manifest_points_to_runtime_resources_only() -> None:
    manifest = _read_yaml_mapping(IDENTITY_ROOT / "manifest.yaml")

    assert manifest["schema_version"] == 2
    assert manifest["bundle_version"] == "0.4.0-draft"

    default_baseline = _as_mapping(manifest["default_baseline"])
    assert default_baseline == {
        "resource_id": "default-chat",
        "path": "common/agent-contract.md",
    }
    characters = _as_mapping(manifest["characters"])
    xiaojin = _as_mapping(characters["xiaojin"])
    assert xiaojin == {
        "resource_id": "xiaojin",
        "path": "characters/xiaojin/manifest.yaml",
    }

    for resource_path in (
        default_baseline["path"],
        xiaojin["path"],
    ):
        assert isinstance(resource_path, str)
        path = (IDENTITY_ROOT / resource_path).resolve()
        assert path.is_relative_to(IDENTITY_ROOT.resolve())
        assert path.is_file()
    assert "golden.yaml" not in (IDENTITY_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    assert not (IDENTITY_ROOT / "characters" / "xiaojin" / "golden.yaml").exists()
    assert not (IDENTITY_ROOT / "characters" / "xiaojin" / "golden" / "golden.yaml").exists()

    character_manifest = _read_yaml_mapping(
        IDENTITY_ROOT / "characters" / "xiaojin" / "manifest.yaml"
    )
    assert character_manifest["schema_version"] == 2
    assert character_manifest["resource_type"] == "character_bundle"
    assert character_manifest["resource_id"] == "xiaojin"
    for key in ("profile", "voice", "relational_dynamics", "capabilities", "memory_preload"):
        resource_spec = _as_mapping(character_manifest[key])
        resource_path = IDENTITY_ROOT / "characters" / "xiaojin" / resource_spec["path"]
        assert resource_path.is_file()

    capabilities = _read_yaml_mapping(
        IDENTITY_ROOT / "characters" / "xiaojin" / "capabilities.yaml"
    )
    assert capabilities["schema_version"] == 2
    assert capabilities["resource_type"] == "character_capabilities"
    assert capabilities["resource_id"] == "xiaojin.capabilities"
    capability_items = capabilities["capabilities"]
    assert isinstance(capability_items, list)
    assert [_as_mapping(item)["name"] for item in capability_items] == ["memory_search"]

    preload = _read_yaml_mapping(IDENTITY_ROOT / "characters" / "xiaojin" / "memory-preload.yaml")
    assert preload["schema_version"] == 2
    assert preload["resource_type"] == "character_memory_preload"
    assert preload["resource_id"] == "xiaojin.memory-preload"
    preload_items = preload["memories"]
    assert isinstance(preload_items, list)
    assert {item["visibility"] for item in map(_as_mapping, preload_items)} == {
        "resident",
        "private",
    }


def test_golden_fixture_is_version_pinned_and_separate_from_runtime_content() -> None:
    golden_path = FIXTURE_ROOT / "xiaojin" / "golden.yaml"
    golden = _read_yaml_mapping(golden_path)

    assert golden["schema_version"] == 1
    assert golden["character_id"] == "xiaojin"
    assert golden["identity_version"] == "0.5.0-draft"
    assert golden["baseline_version"] == "0.6.1-draft"
    assert golden["prompt_layout_version"] == 8
    assert not {"based_on_identity", "fixture_notes", "checks"}.intersection(golden)

    common_forbid = golden["common_forbid"]
    assert isinstance(common_forbid, list) and common_forbid
    for rule in common_forbid:
        rule_mapping = _as_mapping(rule)
        assert isinstance(rule_mapping["pattern"], str)
        re.compile(rule_mapping["pattern"])
        assert isinstance(rule_mapping["why"], str) and rule_mapping["why"].strip()

    scenarios = golden["scenarios"]
    assert isinstance(scenarios, list) and scenarios
    for scenario in scenarios:
        scenario_mapping = _as_mapping(scenario)
        context = _as_mapping(scenario_mapping["context"])
        assert context["relationship_type"] in {"stranger", "acquaintance", "friend"}
        assert context["world_phase"] == "solo"
        turns = scenario_mapping["turns"]
        assert isinstance(turns, list) and turns
        for turn in turns:
            turn_mapping = _as_mapping(turn)
            expectations = turn_mapping["review_expectations"]
            references = turn_mapping["ref"]
            assert isinstance(expectations, list) and all(
                isinstance(item, str) and item.strip() for item in expectations
            )
            assert isinstance(references, list) and all(
                isinstance(item, str) and item.strip() for item in references
            )


def test_change_logs_are_kept_outside_runtime_prompt_files() -> None:
    baseline_changelog = IDENTITY_ROOT / "common" / "agent-contract.changelog.md"
    identity_changelog = IDENTITY_ROOT / "characters" / "xiaojin" / "identity.changelog.md"

    assert baseline_changelog.exists()
    assert identity_changelog.exists()
    assert "0.6.1-draft" in baseline_changelog.read_text(encoding="utf-8")
    assert "0.5.0-draft" in identity_changelog.read_text(encoding="utf-8")
