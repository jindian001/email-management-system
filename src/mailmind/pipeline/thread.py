"""会话（thread）归并与主题规范化。

归并规则（exp.md 4.1/4.3）：
1. 有 References → 取第一个引用作为根；
2. 只有 In-Reply-To → 用它；
3. 都没有 → ``主题(去 Re:) + 发件人`` 的稳定哈希。
"""

from __future__ import annotations

import hashlib
import re

from mailmind.pipeline.parse import ParsedMail, normalize_subject


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def thread_id_for(parsed: ParsedMail) -> str:
    if parsed.references:
        return f"t-{_hash(parsed.references[0])}"
    if parsed.in_reply_to:
        return f"t-{_hash(parsed.in_reply_to[0])}"
    subject = normalize_subject(parsed.subject).lower()
    subject = re.sub(r"\s+", " ", subject)
    return f"t-{_hash(f'{parsed.from_addr}|{subject}')}"


def thread_depth(parsed: ParsedMail) -> int:
    """会话深度：引用链长度，用于自动回复的防回环判断。"""
    ids = {r for r in parsed.references if r}
    for value in parsed.in_reply_to:
        ids.add(value)
    return len(ids)
