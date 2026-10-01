from __future__ import annotations

import re
import unicodedata

import jieba

# Keep this deliberately small and local.  It is part of the on-disk search
# contract: changing it requires rebuilding the sparse projection.
_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "呢",
        "吗",
        "啊",
        "呀",
        "吧",
        "哦",
        "嗯",
        "我",
        "你",
        "他",
        "她",
        "它",
        "这",
        "那",
        "是",
        "有",
        "在",
        "和",
        "与",
        "也",
        "都",
        "就",
        "还",
        "很",
        "又",
        "或",
        "及",
        "而",
        "不",
        "没",
    }
)
_WORD_RE = re.compile(r"[\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", re.UNICODE)


def _normalize_token(token: str) -> str:
    return "".join(token.strip().lower().split())


def _is_searchable(token: str) -> bool:
    if not token or token in _STOPWORDS:
        return False
    # Jieba can return punctuation and emoji as standalone tokens.  Keep a
    # token only when it contains at least one letter, number, or CJK codepoint.
    return any(
        (char.isalnum() or "\u3400" <= char <= "\u9fff") and unicodedata.category(char)[0] != "P"
        for char in token
    )


def tokenize_text(text: str) -> tuple[str, ...]:
    """Return stable, de-duplicated jieba tokens suitable for FTS5."""

    if not isinstance(text, str):
        return ()
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in jieba.cut_for_search(text, HMM=False):
        for candidate in _WORD_RE.findall(_normalize_token(raw)):
            if not _is_searchable(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            tokens.append(candidate)
    return tuple(tokens)


def tokenized_text(text: str) -> str:
    """Return the representation persisted in the FTS5 index."""

    return " ".join(tokenize_text(text))


def fts_match_query(text: str) -> str | None:
    """Build a quoted OR query, or ``None`` when no meaningful term exists."""

    tokens = tokenize_text(text)
    if not tokens:
        return None
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


__all__ = ["fts_match_query", "tokenize_text", "tokenized_text"]
