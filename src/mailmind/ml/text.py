"""分词与文本工具。

中文不做词典分词，直接用 **字 unigram + bigram**（exp.md 4.6.3）：
短文本上更稳，且省掉词典维护与 OOV 问题。
"""

from __future__ import annotations

import re

_LATIN_RE = re.compile(r"[a-z0-9][a-z0-9._%+'-]*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_URL_RE = re.compile(r"https?://\S+", re.I)


def tokenize(text: str, *, max_tokens: int = 4000) -> list[str]:
    if not text:
        return []
    text = text.lower()
    text = _URL_RE.sub(" __url__ ", text)
    tokens: list[str] = _LATIN_RE.findall(text)
    for run in _CJK_RE.findall(text):
        for ch in run:
            tokens.append(ch)
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens[:max_tokens]


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    """关键词命中（大小写不敏感，支持中文子串）。"""
    lowered = (text or "").lower()
    return [kw for kw in keywords if kw.lower() in lowered]
