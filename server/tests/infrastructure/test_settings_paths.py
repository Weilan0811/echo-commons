import os
from importlib.resources import files
from pathlib import Path

import pytest

from echo_commons.app.settings import _SECTION_FIELDS, load_settings


def test_defaults_and_explicit_paths_use_settings_directory(tmp_path):
    config = tmp_path / "project" / "config"
    config.mkdir(parents=True)
    path = config / "settings.toml"
    path.write_text("schema_version = 1\n", encoding="utf-8")
    first = load_settings(path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    previous = Path.cwd()
    try:
        os.chdir(other)
        second = load_settings(path)
    finally:
        os.chdir(previous)
    assert first == second
    assert Path(first.database_path) == config.parent / "data/echo-commons.sqlite3"
    assert Path(first.model_registry_path) == config / "model-registry.toml"
    assert Path(first.model_secrets_path) == config / "model-secrets.toml"
    assert Path(first.debug_capture_path) == config.parent / "data/debug-captures"
    assert first.identity_root is None
    path.write_text(
        'schema_version = 1\n[storage]\ndatabase_path = "custom.sqlite3"\n'
        '[identity]\nroot = "../characters"\n[observability]\nlog_path = "logs/run.log"\n',
        encoding="utf-8",
    )
    explicit = load_settings(path)
    assert Path(explicit.database_path) == config / "custom.sqlite3"
    assert Path(explicit.identity_root) == config.parent / "characters"
    assert Path(explicit.log_path) == config / "logs/run.log"


@pytest.mark.parametrize(
    "body",
    (
        "[server]\nmax_responders = 2",
        "[workers]\ndatabase_path = 'misplaced.sqlite3'",
        "[identity]\nidentity_root = 'misplaced'",
        "[reflection.generation]\nexecution_timeout_seconds = 30",
        "[conversation.generation]\nport = 8765",
        "[conversation]\ngeneration = 3",
        "[unknown]\nport = 8765",
    ),
)
def test_unknown_or_misplaced_fields_are_rejected(tmp_path, body):
    path = tmp_path / "settings.toml"
    path.write_text(f"schema_version = 1\n{body}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path)


def test_template_and_section_map_cover_all_settings(tmp_path):
    from echo_commons.app.settings import Settings

    renames = {
        "identity.root": "identity_root",
        "model.registry_path": "model_registry_path",
        "model.secrets_path": "model_secrets_path",
        "workers.enabled": "worker_enabled",
        "workers.poll_interval_seconds": "worker_poll_interval_seconds",
    }
    mapped = set()
    for section, keys in _SECTION_FIELDS.items():
        if section == "memory":
            mapped.add("memory")
            continue
        for key in keys:
            if key == "generation":
                mapped.update(
                    f"{section}_{name}" for name in ("temperature", "top_p", "max_output_tokens")
                )
            else:
                mapped.add(
                    renames.get(
                        f"{section}.{key}", f"reflection_{key}" if section == "reflection" else key
                    )
                )
    assert mapped == Settings.model_fields.keys()
    path = tmp_path / "settings.toml"
    path.write_text(
        files("echo_commons.resources.config")
        .joinpath("settings.toml")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert Path(settings.model_registry_path) == tmp_path / "model-registry.toml"
