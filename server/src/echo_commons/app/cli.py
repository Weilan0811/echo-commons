import argparse
import json

from echo_commons.app.settings import load_settings
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog


def main() -> None:
    parser = argparse.ArgumentParser(prog="echo-commons")
    parser.add_argument("--settings", default="config/settings.toml")
    parser.add_argument("command", choices=("inspect",))
    arguments = parser.parse_args()
    settings = load_settings(arguments.settings)
    catalog = load_blueprint_catalog(settings.identity_root)
    registry = load_model_registry(settings.model_registry_path, settings.model_secrets_path)
    print(
        json.dumps(
            {
                "database_path": settings.database_path,
                "blueprints": list(catalog.blueprints),
                "model_profile": registry.active_profile,
                "configured": registry.credential_for(registry.resolve()) is not None,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
