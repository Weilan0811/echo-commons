import argparse
import ast
from pathlib import Path


def reference(root: Path) -> str:
    source = root / "src/echo_commons"
    groups: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(source.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(source)
        group = "/".join(
            relative.parts[:2] if relative.parts[0] == "modules" else relative.parts[:1]
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definitions = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        groups.setdefault(group, []).append(
            (relative.as_posix(), ", ".join(definitions) or "常量与类型")
        )
    lines = [
        "# 实际后端文件导航\n",
        "路径相对 `server/src/echo_commons/`。先按业务模块查找，"
        "再按领域、服务、存储、接口和任务查找。",
        "入口列直接读取当前 Python 顶层类型与函数；具体职责见 [系统设计](../design/system.md)。",
        "每个 Python 包有明确的 `__init__.py`；"
        "包初始化只承担版本声明或包登记，不重复导出业务定义。\n",
        "重新生成：`uv run python tools/build_file_reference.py`；增加 `--check` 验证当前列表。\n",
    ]
    for group, entries in groups.items():
        lines.extend([f"\n## `{group}/`\n", "| 文件 | 类型与入口 |", "|---|---|"])
        lines.extend(f"| `{path}` | {definitions} |" for path, definitions in entries)
    lines.extend(
        [
            "\n## 工程与资源\n",
            "配置、模型凭据与命令见 [服务说明](../../README.md)。",
            "resources/identity 保存完整模板、声音风格和初始记忆；"
            "resources/config 保存非秘密配置模板；",
            "resources/prompts 保存聊天与反思提示正文；"
            "resources/authoring 保存创作模板、采访题库与创作提示；",
            "resources/examples/group.json 保存显式示例。"
            "正式 SQL 与实际字段见 [数据库](database-schema.md)。",
            "tests/infrastructure 保存真实 SQLite、服务、HTTP、进程恢复和模型验证。",
            "tools 保存安装验证与文档生成命令；阶段记录保存实际验证结果。\n",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "docs/reference/source-map.md"
    content = reference(root)
    if arguments.check:
        if target.read_text(encoding="utf-8") != content:
            raise ValueError("File reference differs from the current code")
    else:
        target.write_text(content, encoding="utf-8")
    print("File reference verified" if arguments.check else "File reference generated")


if __name__ == "__main__":
    main()
