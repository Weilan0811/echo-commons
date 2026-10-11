from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    documents = sorted((root / "docs").glob("*.md"))
    documents += sorted((root / "server/docs").rglob("*.md"))
    documents += sorted((root / "frontend/docs").rglob("*.md"))
    documents.append(root / "server/README.md")
    parser = MarkdownIt("commonmark").enable("table")
    failures = []
    for document in documents:
        for token in parser.parse(document.read_text(encoding="utf-8")):
            for child in token.children or ():
                if child.type != "link_open":
                    continue
                target = urlsplit(child.attrGet("href") or "")
                if target.scheme or not target.path:
                    continue
                destination = document.parent / unquote(target.path)
                if not destination.exists():
                    failures.append(f"{document.relative_to(root)}: {target.path}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated local links in {len(documents)} documents.")


if __name__ == "__main__":
    main()
