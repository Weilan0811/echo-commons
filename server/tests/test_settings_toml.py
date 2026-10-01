from pathlib import Path

from echo_server.config import load_settings


def test_roleplay_settings_are_loaded_from_toml(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config" / "settings.toml"
    config = tmp_path / "settings.toml"
    content = source.read_text(encoding="utf-8")
    content = content.replace("quiet_window_seconds = 6", "quiet_window_seconds = 2")
    content = content.replace("recent_message_max_chars = 6000", "recent_message_max_chars = 3000")
    content = content.replace("memory_search_max_results = 5", "memory_search_max_results = 3")
    content = content.replace("# temperature = 0.7", "temperature = 0.7", 1).replace(
        "# top_p = 0.9", "top_p = 0.9", 1
    )
    config.write_text(content, encoding="utf-8")

    settings = load_settings(config)

    assert settings.quiet_window_seconds == 2
    assert settings.recent_message_max_chars == 3000
    assert settings.memory_search_max_results == 3
    assert settings.conversation_temperature == 0.7
    assert settings.conversation_top_p == 0.9
    assert settings.reflection_temperature is None
    assert settings.reflection_max_candidates == 64
    assert settings.reflection_max_output_chars == 20_000
    assert settings.database_path == str((tmp_path / ".." / "data" / "echo.sqlite3").resolve())
