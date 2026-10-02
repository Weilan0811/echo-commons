import ast
import difflib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "400defb"
INITIAL = "0a14ed4"
EVIDENCE = ROOT / "docs/prompt-audit"
PREFIX = "server/src/echo_commons/"


def original(path: str, revision: str = BASELINE) -> str:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")


def current(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def literals(source: str) -> list[tuple[int, str]]:
    # AST 保留 Python 解码后的实际字符串，比较时不改写空白或标点。
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def write(name: str, value: str) -> None:
    (EVIDENCE / name).write_text(value, encoding="utf-8", newline="\n")


def difference(name: str, old_path: str, new_path: str) -> dict[str, object]:
    old, new = original(old_path), current(new_path)
    write(
        name + ".diff",
        "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"{BASELINE}/{old_path}",
                tofile=f"working-tree/{new_path}",
            )
        ),
    )
    return {"original": old_path, "current": new_path, "text_equal": old == new}


def main() -> None:
    sys.path.insert(0, str(ROOT / "server/src"))
    from echo_commons.modules.characters.templates.loader import _read_frontmatter

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    paths = (
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", BASELINE, "server"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .splitlines()
    )
    source_index: dict[str, list[str]] = {}
    for path in (ROOT / PREFIX).rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        for line, value in literals(path.read_text(encoding="utf-8")):
            source_index.setdefault(value, []).append(f"{relative}:{line}")

    old_prompt_path = PREFIX + "agents/harness/prompt.py"
    old_prompt = original(old_prompt_path)
    write("original-prompt.py.txt", old_prompt)
    write(
        "current-conversation-prompt.py.txt",
        current(PREFIX + "modules/conversations/tasks/prompt.py"),
    )
    write(
        "current-reflection-prompt.py.txt", current(PREFIX + "modules/reflection/tasks/prompt.py")
    )
    fixed = [
        {
            "line": line,
            "text": value,
            "exact_occurrences_in_current_source": source_index.get(value, []),
        }
        for line, value in literals(old_prompt)
        if any("\u4e00" <= char <= "\u9fff" for char in value)
    ]
    write("fixed-text-comparison.json", json.dumps(fixed, ensure_ascii=False, indent=2) + "\n")
    functions = []
    for node in ast.parse(old_prompt).body:
        if isinstance(node, ast.FunctionDef):
            entries = [item for item in fixed if node.lineno <= item["line"] <= node.end_lineno]
            functions.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "chinese_literal_count": len(entries),
                    "exact_literal_occurrences": sum(
                        bool(item["exact_occurrences_in_current_source"]) for item in entries
                    ),
                }
            )

    paired = {}
    for name, old_name, new_name in (
        ("context", "agents/harness/context.py", "agents/harness/context.py"),
        ("loop", "agents/harness/loop.py", "agents/harness/loop.py"),
        ("recovery", "agents/harness/recovery.py", "agents/harness/recovery.py"),
        ("memory-search", "runtime/memory/search_tool.py", "modules/memory/tools/search.py"),
        ("output-contract", "agents/contracts/proposals.py", "agents/contracts/output.py"),
        (
            "reflection-candidates",
            "agents/contracts/reflection.py",
            "modules/reflection/contracts/candidates.py",
        ),
        ("review-recovery", "runtime/recovery.py", "execution/recovery.py"),
        (
            "model-request",
            "services/model_gateway/openai_compatible.py",
            "infrastructure/models/openai_compatible.py",
        ),
    ):
        paired[name] = difference(name, PREFIX + old_name, PREFIX + new_name)

    resources = []
    for suffix in (
        "common/agent-contract.md",
        "characters/xiaojin/profile.md",
        "characters/xiaojin/voice.md",
        "characters/xiaojin/relational-dynamics.md",
        "characters/xiaojin/capabilities.yaml",
        "characters/xiaojin/memory-preload.yaml",
        "characters/xiaojin/manifest.yaml",
        "manifest.yaml",
    ):
        old_path = "server/config/identity/" + suffix
        new_path = PREFIX + "resources/identity/" + suffix.replace("characters/", "blueprints/")
        result = difference(
            "resource-" + suffix.replace("/", "-").rsplit(".", 1)[0], old_path, new_path
        )
        old, new = original(old_path), current(new_path)
        result["initial_baseline_equal"] = original(old_path, INITIAL) == old
        if suffix.endswith(".md"):
            old_meta, old_body = _read_frontmatter(old.splitlines(), "original")
            new_meta, new_body = _read_frontmatter(new.splitlines(), "current")
            result.update(body_equal=old_body == new_body, metadata_equal=old_meta == new_meta)
        else:
            old_yaml, new_yaml = yaml.safe_load(old), yaml.safe_load(new)
            for field in ("capabilities", "memories"):
                if field in old_yaml or field in new_yaml:
                    result[field + "_equal"] = old_yaml.get(field) == new_yaml.get(field)
        resources.append(result)

    # 扫描历史源码以供人工检查提示入口，命中字符串本身不等于模型会读到。
    historical = []
    for path in paths:
        if path.startswith(PREFIX) and path.endswith(".py"):
            entries = [
                {"line": line, "text": value}
                for line, value in literals(original(path))
                if any("\u4e00" <= char <= "\u9fff" for char in value)
            ]
            if entries:
                historical.append({"path": path, "strings": entries})
    write(
        "historical-chinese-literals.json",
        json.dumps(historical, ensure_ascii=False, indent=2) + "\n",
    )
    result = {
        "baseline": BASELINE,
        "initial": INITIAL,
        "original_prompt_initial_equal": original(old_prompt_path, INITIAL) == old_prompt,
        "fixed_text_count": len(fixed),
        "fixed_text_found_in_current_source": sum(
            bool(item["exact_occurrences_in_current_source"]) for item in fixed
        ),
        "functions": functions,
        "resources": resources,
        "paired_sources": paired,
        "comparison": (
            "Exact decoded Python strings; Markdown bodies use the production loader; "
            "no model calls."
        ),
    }
    old_recovery = ast.parse(original(PREFIX + "agents/harness/recovery.py"))
    new_recovery = ast.parse(current(PREFIX + "agents/harness/recovery.py"))
    hints = []
    for tree in (old_recovery, new_recovery):
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_REPAIR_HINTS"
                for target in node.targets
            )
        )
        hints.append(ast.literal_eval(assignment.value))
    result["repair_hints"] = [
        {
            "code": code,
            "original": value,
            "current": hints[1].get(code),
            "equal": value == hints[1].get(code),
        }
        for code, value in hints[0].items()
    ]
    old_loop = [
        value
        for _, value in literals(original(PREFIX + "agents/harness/loop.py"))
        if any("\u4e00" <= char <= "\u9fff" for char in value)
    ]
    new_loop = [
        value
        for _, value in literals(current(PREFIX + "agents/harness/loop.py"))
        if any("\u4e00" <= char <= "\u9fff" for char in value)
    ]
    result["loop_chinese_literal_multiset_equal"] = sorted(old_loop) == sorted(new_loop)
    result["loop_chinese_literal_count"] = len(old_loop)
    old_gateway = ast.parse(original(PREFIX + "services/model_gateway/openai_compatible.py"))
    new_gateway = ast.parse(current(PREFIX + "infrastructure/models/openai_compatible.py"))
    old_payload = next(
        node
        for node in old_gateway.body
        if isinstance(node, ast.FunctionDef) and node.name == "_prompt_message_payload"
    )
    new_payload = next(
        node
        for node in new_gateway.body
        if isinstance(node, ast.FunctionDef) and node.name == "_prompt_message_payload"
    )
    result["provider_message_serialization_ast_equal"] = ast.dump(old_payload) == ast.dump(
        new_payload
    )
    write("results.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
