import argparse
import json
from pathlib import Path

from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "docs/reference"
    # 只构造接口和类型，未进入应用生命周期，不读取密钥或调用模型。
    documents = {
        "openapi.json": create_app(Settings()).openapi(),
        "settings-schema.json": Settings.model_json_schema(),
    }
    for name, value in documents.items():
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        path = target / name
        if arguments.check:
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"Contract reference differs: {name}")
        else:
            path.write_text(content, encoding="utf-8")
    print("Contract references verified" if arguments.check else "Contract references generated")


if __name__ == "__main__":
    main()
