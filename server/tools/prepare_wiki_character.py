import argparse
import asyncio
import json
from pathlib import Path

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.modules.characters.services.wiki_authoring import WikiAuthoring


async def prepare(arguments):
    settings = load_settings(arguments.settings).model_copy(
        update={
            "database_path": str(arguments.output.parent / "community.sqlite3"),
            "asset_directory": str(arguments.output.parent / "assets"),
            "worker_enabled": False,
            "log_path": str(arguments.output.parent / "verification.log"),
        }
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    async with application_lifecycle(settings) as application:
        result = await WikiAuthoring(application.authoring).prepare(
            arguments.url,
            arguments.name,
            scope=arguments.scope,
            source_text=arguments.source.read_text(encoding="utf-8") if arguments.source else None,
        )
        arguments.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                dict(
                    output=str(arguments.output),
                    name=result["proposal"]["display_name"],
                    relationships=len(result["proposal"]["relationship_suggestions"]),
                ),
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser(description="整理百科创作候选，人物编号由作者确认后另行登记")
    parser.add_argument("url")
    parser.add_argument("name")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--scope", default="")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(prepare(parser.parse_args()))


if __name__ == "__main__":
    main()
