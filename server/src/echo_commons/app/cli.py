import argparse
import asyncio
import json
from importlib.resources import files
from pathlib import Path

import uvicorn

from echo_commons.app.composition import assemble
from echo_commons.app.development import (
    ExampleCommunity,
    export_database,
    initialize_example,
    inspect_database,
)
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings


async def execute(arguments) -> dict:
    settings = load_settings(arguments.settings).model_copy(update={"worker_enabled": False})
    if arguments.command == "init":
        example = None
        if arguments.example:
            source = (
                files("echo_commons").joinpath("resources/examples/group.json")
                if arguments.example == "group"
                else Path(arguments.example)
            )
            example = ExampleCommunity.model_validate_json(source.read_text(encoding="utf-8"))
        async with application_lifecycle(settings) as application:
            result = initialize_example(application, example) if example else {}
            return {**inspect_database(application), **result}
    application = assemble(settings, read_only=True)
    try:
        if arguments.command == "export":
            return export_database(application, Path(arguments.output))
        return inspect_database(application)
    finally:
        await application.image_generations.gateway.close()
        await application.gateway.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="echo-commons")
    parser.add_argument("--settings", default="config/settings.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure")
    configure.add_argument("--directory", default="config")
    initialize = commands.add_parser("init")
    initialize.add_argument("--example", nargs="?", const="group")
    commands.add_parser("inspect")
    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    commands.add_parser("serve")
    arguments = parser.parse_args()
    if arguments.command == "configure":
        directory = Path(arguments.directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        resource = files("echo_commons").joinpath("resources/config")
        for name in ("settings.toml", "model-registry.toml"):
            if (directory / name).exists():
                raise FileExistsError(directory / name)
        for name in ("settings.toml", "model-registry.toml"):
            with (directory / name).open("xb") as target:
                target.write(resource.joinpath(name).read_bytes())
        secrets = directory / "model-secrets.toml"
        if not secrets.exists():
            with secrets.open("xb") as target:
                target.write(resource.joinpath("model-secrets.example.toml").read_bytes())
        result = {"settings_path": str(directory / "settings.toml")}
    elif arguments.command == "serve":
        settings = load_settings(arguments.settings)
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
        return
    else:
        result = asyncio.run(execute(arguments))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
